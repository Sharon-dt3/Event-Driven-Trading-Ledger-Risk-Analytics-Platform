package com.tradepulse.ledger.web;

import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HealthController {

    @GetMapping("/health")
    public Map<String, Object> health() {
        return Map.of("status", "UP", "service", "ledger-core");
    }

    @GetMapping("/")
    public Map<String, Object> root() {
        return Map.of("service", "ledger-core", "version", "0.4.0");
    }
}
