package com.tradepulse.ledger.domain;

/** Credentials payload for POST /auth/login (contract: LoginRequest). */
public record LoginRequest(String username, String password) {
}
