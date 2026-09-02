package com.tradepulse.ledger.web;

import com.tradepulse.ledger.domain.LoginRequest;
import com.tradepulse.ledger.domain.LoginResponse;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/** Authentication endpoint: exchanges credentials for a JWT. */
@RestController
public class AuthController {

    private final AuthService authService;
    private final TokenService tokenService;

    public AuthController(AuthService authService, TokenService tokenService) {
        this.authService = authService;
        this.tokenService = tokenService;
    }

    @PostMapping("/auth/login")
    public ResponseEntity<LoginResponse> login(@RequestBody LoginRequest request) {
        if (request == null || request.username() == null || request.password() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "username and password required");
        }
        return authService.authenticate(request.username(), request.password())
                .map(role -> ResponseEntity.ok(
                        new LoginResponse(tokenService.mint(request.username(), role), "Bearer", role)))
                .orElseThrow(() ->
                        new ResponseStatusException(HttpStatus.UNAUTHORIZED, "invalid credentials"));
    }
}
