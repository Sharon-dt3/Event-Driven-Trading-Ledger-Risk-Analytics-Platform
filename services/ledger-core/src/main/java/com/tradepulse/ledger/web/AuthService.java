package com.tradepulse.ledger.web;

import java.util.Map;
import java.util.Optional;
import org.springframework.stereotype.Service;

/**
 * Minimal credential store for issuing JWTs. These are DEMO credentials for the
 * POC; a production build would authenticate against the users table with hashed
 * passwords. Roles match the frozen contract (viewer/trader/compliance/admin).
 */
@Service
public class AuthService {

    private record Credential(String password, String role) {
    }

    private final Map<String, Credential> users = Map.of(
            "demo_trader", new Credential("trader-pw", "trader"),
            "viewer", new Credential("viewer-pw", "viewer"),
            "compliance", new Credential("compliance-pw", "compliance"),
            "admin", new Credential("admin-pw", "admin"));

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
