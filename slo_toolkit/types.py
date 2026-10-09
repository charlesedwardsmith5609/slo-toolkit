"""Shared enums and typed constants for slo-toolkit."""

from __future__ import annotations

from enum import Enum


class BurnRateStatus(str, Enum):
    """Burn-rate severity for a single observation."""

    OK = "OK"
    ELEVATED = "ELEVATED"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EXHAUSTED = "EXHAUSTED"


class SLIType(str, Enum):
    """
    Service level indicator shape.

    Affects metric contracts and alert copy — not the burn-rate math itself,
    which is always good/bad event (or error-rate) based.
    """

    AVAILABILITY = "availability"
    LATENCY = "latency"
    FRESHNESS = "freshness"


class AlertSeverity(str, Enum):
    PAGE = "page"
    TICKET = "ticket"
    INFO = "info"


class ProjectionMode(str, Enum):
    """How to project end-of-window compliance."""

    # Request-based SLIs: if observed error *rate* continues, EOW rate ≈ rate now.
    CONSTANT_RATE = "constant_rate"
    # Calendar heuristic: treat rate-budget ratio as pace and scale by window/elapsed.
    # Useful for storytelling; misleading for pure request-based budgets.
    TIME_PACE = "time_pace"


# Versioned alert config JSON schema (bump when breaking export shape).
ALERT_CONFIG_SCHEMA_VERSION = "1.0"
