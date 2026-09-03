package com.tradepulse.ledger.web;

import com.tradepulse.ledger.domain.AdminCreditRequest;
import com.tradepulse.ledger.domain.AdminCreditResult;
import com.tradepulse.ledger.ledger.LedgerService;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * Admin-only operations. Every route under /admin/** is restricted to the
 * {@code admin} role by SecurityConfig, giving admin strictly more power than a
 * trader (who can place trades but cannot fund accounts).
 */
@RestController
public class AdminController {

    private final LedgerService ledgerService;

    public AdminController(LedgerService ledgerService) {
        this.ledgerService = ledgerService;
    }

    /** Fund an account with additional cash (admin only). */
    @PostMapping("/admin/accounts/{accountId}/credit")
    public ResponseEntity<AdminCreditResult> credit(@PathVariable String accountId,
                                                    @RequestBody AdminCreditRequest request) {
        if (request == null || request.amount() == null || request.amount().signum() <= 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "amount must be > 0");
        }
        if (!ledgerService.accountExists(accountId)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "unknown account_id");
        }
        return ResponseEntity.ok(
                ledgerService.creditAccount(accountId, request.amount(), request.reason()));
    }
}
