package com.tradepulse.ledger.web;

import java.util.Map;
import java.util.Optional;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * Minimal credential store for issuing JWTs. Passwords are injected from
 * configuration so that real deployments override them via environment
 * variables (LEDGER_AUTH_*_PASSWORD) instead of shipping secrets in source.
 * The defaults below are DEMO credentials for local development only; a full
 * production build would authenticate against the users table with hashed
 * passwords. Roles match the frozen contract (viewer/trader/compliance/admin).
 */
@Service
public class AuthService {

    private record Credential(String password, String role) {
    }

    private final Map<String, Credential> users;

    public AuthService(
            @Value("${ledger.auth.trader-password:trader-pw}") String traderPassword,
            @Value("${ledger.auth.viewer-password:viewer-pw}") String viewerPassword,
            @Value("${ledger.auth.compliance-password:compliance-pw}") String compliancePassword,
            @Value("${ledger.auth.admin-password:admin-pw}") String adminPassword) {
        this.users = Map.of(
                "demo_trader", new Credential(traderPassword, "trader"),
                "viewer", new Credential(viewerPassword, "viewer"),
                "compliance", new Credential(compliancePassword, "compliance"),
                "admin", new Credential(adminPassword, "admin"));
    }

    /** Returns the user's role if the credentials are valid. */
    public Optional<String> authenticate(String username, String password) {
        if (username == null || password == null) {
            return Optional.empty();
        }
        Credential cred = users.get(username);
        if (cred != null && cred.password().equals(password)) {
            return Optional.of(cred.role());
        }
        return Optional.empty();
    }
}
