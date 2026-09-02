package com.tradepulse.ledger.web;

import com.tradepulse.ledger.domain.AuditEntryDto;
import com.tradepulse.ledger.domain.BalanceDto;
import com.tradepulse.ledger.domain.PositionDto;
import com.tradepulse.ledger.domain.TradeRequestDto;
import com.tradepulse.ledger.domain.TradeResultDto;
import com.tradepulse.ledger.ledger.LedgerReadService;
import com.tradepulse.ledger.ledger.LedgerService;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * Ledger REST API (behind the ALB /ledger route). Phase 2 implements trade
 * submission plus balance/history/audit reads against the system-of-record.
 */
@RestController
public class TradeController {

    private final LedgerService ledgerService;
    private final LedgerReadService readService;

    public TradeController(LedgerService ledgerService, LedgerReadService readService) {
        this.ledgerService = ledgerService;
        this.readService = readService;
    }

    @PostMapping("/trades")
    public ResponseEntity<TradeResultDto> submitTrade(@RequestBody TradeRequestDto request) {
        validate(request);
        if (!ledgerService.accountExists(request.account_id())) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "unknown account_id");
        }
        LedgerService.PostOutcome outcome = ledgerService.postTrade(request);
        TradeResultDto result = outcome.result();

        if ("rejected".equals(result.status())) {
            return ResponseEntity.status(HttpStatus.CONFLICT).body(result); // 409, still audited
        }
        HttpStatus status = outcome.created() ? HttpStatus.CREATED : HttpStatus.OK;
        return ResponseEntity.status(status).body(result);
    }

    @GetMapping("/trades")
    public List<TradeResultDto> history(@RequestParam(required = false) String account_id,
                                        @RequestParam(required = false) String status) {
        return readService.history(account_id, status);
    }

    @GetMapping("/balances")
    public List<BalanceDto> balances(@RequestParam(required = false) String account_id) {
        return readService.balances(account_id);
    }

    @GetMapping("/positions")
    public List<PositionDto> positions(@RequestParam(required = false) String account_id) {
        return readService.positions(account_id);
    }

    @GetMapping("/audit")
    public List<AuditEntryDto> audit(@RequestParam(required = false) String account_id) {
        return readService.audit(account_id);
    }

    private void validate(TradeRequestDto r) {
        if (r == null || r.request_id() == null || r.account_id() == null || r.symbol() == null
                || r.side() == null || r.quantity() == null || r.price() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "missing required trade fields");
        }
        if (!"BUY".equals(r.side()) && !"SELL".equals(r.side())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "side must be BUY or SELL");
        }
        if (r.quantity().signum() <= 0 || r.price().signum() <= 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "quantity and price must be > 0");
        }
    }
}
