package com.tradepulse.ledger.ledger;

import com.tradepulse.ledger.domain.AuditEntryDto;
import com.tradepulse.ledger.domain.BalanceDto;
import com.tradepulse.ledger.domain.PositionDto;
import com.tradepulse.ledger.domain.TradeResultDto;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Read-only queries for the ledger REST API. */
@Service
public class LedgerReadService {

    private final LedgerRepository repo;

    public LedgerReadService(LedgerRepository repo) {
        this.repo = repo;
    }

    @Transactional(readOnly = true)
    public List<TradeResultDto> history(String accountId, String status) {
        return repo.history(accountId, status);
    }

    @Transactional(readOnly = true)
    public List<BalanceDto> balances(String accountId) {
        return repo.balances(accountId);
    }

    @Transactional(readOnly = true)
    public List<PositionDto> positions(String accountId) {
        return repo.positions(accountId);
    }

    @Transactional(readOnly = true)
    public List<AuditEntryDto> audit(String accountId) {
        return repo.audit(accountId);
    }
}
