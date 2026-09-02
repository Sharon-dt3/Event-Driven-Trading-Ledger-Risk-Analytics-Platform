package com.tradepulse.ledger;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.ResponseEntity;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class LedgerCoreApplicationTests {

    @LocalServerPort
    int port;

    @Autowired
    TestRestTemplate restTemplate;

    @Test
    void contextLoads() {
    }

    @Test
    void healthEndpointReturnsUp() {
        ResponseEntity<String> response =
                restTemplate.getForEntity("http://localhost:" + port + "/health", String.class);
        assertThat(response.getStatusCode().is2xxSuccessful()).isTrue();
        assertThat(response.getBody()).contains("UP");
    }

    @Test
    void correlationIdHeaderIsEchoed() {
        ResponseEntity<String> response =
                restTemplate.getForEntity("http://localhost:" + port + "/health", String.class);
        assertThat(response.getHeaders().getFirst("X-Correlation-ID")).isNotBlank();
    }
}
