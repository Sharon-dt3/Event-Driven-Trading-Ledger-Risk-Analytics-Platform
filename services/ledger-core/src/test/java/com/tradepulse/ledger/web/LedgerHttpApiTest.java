package com.tradepulse.ledger.web;

import static org.assertj.core.api.Assertions.assertThat;

import com.tradepulse.ledger.domain.LoginRequest;
import com.tradepulse.ledger.domain.LoginResponse;
import com.tradepulse.ledger.domain.TradeRequestDto;
import com.tradepulse.ledger.domain.TradeResultDto;
import java.math.BigDecimal;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * Phase 4 acceptance over HTTP:
 *  - the API requires a JWT (401 without one);
 *  - /auth/login mints a token;
 *  - duplicate trade requests (same request_id) do NOT double-post — proven both
 *    at the HTTP layer (201 then 200) and in the database (exactly one journal
 *    entry, unchanged cash).
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class LedgerHttpApiTest {

    @LocalServerPort
    int port;

    @Autowired
    TestRestTemplate rest;

    @Autowired
    JdbcTemplate jdbc;

    private String url(String path) {
        return "http://localhost:" + port + path;
    }

    private String login() {
        ResponseEntity<LoginResponse> resp = rest.postForEntity(
                url("/auth/login"), new LoginRequest("demo_trader", "trader-pw"), LoginResponse.class);
        assertThat(resp.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(resp.getBody()).isNotNull();
        assertThat(resp.getBody().role()).isEqualTo("trader");
        return resp.getBody().access_token();
    }

    private HttpEntity<TradeRequestDto> authedTrade(String token, TradeRequestDto body) {
        HttpHeaders headers = new HttpHeaders();
        headers.setBearerAuth(token);
        return new HttpEntity<>(body, headers);
    }

    private TradeRequestDto buy(UUID rid) {
        return new TradeRequestDto(rid, "acct_123", "MSFT", "BUY",
                BigDecimal.valueOf(3), BigDecimal.valueOf(100.0), "user_42");
    }

    @Test
    void trades_requireAuthentication() {
        ResponseEntity<String> resp = rest.postForEntity(
                url("/trades"), buy(UUID.randomUUID()), String.class);
        assertThat(resp.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
    }

    @Test
    void login_invalidCredentials_returns401() {
        ResponseEntity<String> resp = rest.postForEntity(
                url("/auth/login"), new LoginRequest("demo_trader", "wrong"), String.class);
        assertThat(resp.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
    }

    @Test
    void duplicateTradeRequests_doNotDoublePost_overHttp() {
        String token = login();
        UUID rid = UUID.randomUUID();

        ResponseEntity<TradeResultDto> first = rest.exchange(
                url("/trades"), HttpMethod.POST, authedTrade(token, buy(rid)), TradeResultDto.class);
        assertThat(first.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        assertThat(first.getBody()).isNotNull();
        assertThat(first.getBody().status()).isEqualTo("posted");

        BigDecimal cashAfterFirst = jdbc.queryForObject(
                "SELECT cash_balance FROM accounts WHERE account_id = 'acct_123'", BigDecimal.class);

        // Same request_id again: idempotent replay -> 200 OK, NOT a second 201.
        ResponseEntity<TradeResultDto> replay = rest.exchange(
                url("/trades"), HttpMethod.POST, authedTrade(token, buy(rid)), TradeResultDto.class);
        assertThat(replay.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(replay.getBody()).isNotNull();
        assertThat(replay.getBody().journal_entry_id())
                .isEqualTo(first.getBody().journal_entry_id());

        // Database proof: exactly one journal entry, cash unchanged by the replay.
        Integer entries = jdbc.queryForObject(
                "SELECT COUNT(*) FROM journal_entries WHERE source_event_id = ?", Integer.class, rid);
        assertThat(entries).isEqualTo(1);
        BigDecimal cashAfterReplay = jdbc.queryForObject(
                "SELECT cash_balance FROM accounts WHERE account_id = 'acct_123'", BigDecimal.class);
        assertThat(cashAfterReplay).isEqualByComparingTo(cashAfterFirst);
    }

    @Test
    void positions_reflectPostedTrades() {
        String token = login();
        rest.exchange(url("/trades"), HttpMethod.POST,
                authedTrade(token, buy(UUID.randomUUID())), TradeResultDto.class);

        HttpHeaders headers = new HttpHeaders();
        headers.setBearerAuth(token);
        ResponseEntity<String> positions = rest.exchange(
                url("/positions?account_id=acct_123"), HttpMethod.GET,
                new HttpEntity<>(headers), String.class);
        assertThat(positions.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(positions.getBody()).contains("MSFT");
    }
}
