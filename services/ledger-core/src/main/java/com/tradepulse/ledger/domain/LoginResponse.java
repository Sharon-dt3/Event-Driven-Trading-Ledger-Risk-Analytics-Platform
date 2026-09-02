package com.tradepulse.ledger.domain;

/** JWT issued by /auth/login (contract: LoginResponse). */
public record LoginResponse(String access_token, String token_type, String role) {
}
