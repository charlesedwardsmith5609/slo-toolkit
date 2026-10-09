"""
slo-toolkit: Calculate burn rates, generate multi-window alert thresholds,
and evaluate SLO compliance for distributed systems.
"""

from .alert_config import AlertConfig, AlertConfigGenerator, MetricContract
from .burn_rate import BurnRateCalculator, BurnRateResult
from .compliance import CompliancePeriod, SLOComplianceReport, WindowProjection
from .types import (
    ALERT_CONFIG_SCHEMA_VERSION,
    AlertSeverity,
    BurnRateStatus,
    ProjectionMode,
    SLIType,
)

__version__ = "0.2.0"
__all__ = [
    "ALERT_CONFIG_SCHEMA_VERSION",
    "AlertConfig",
    "AlertConfigGenerator",
    "AlertSeverity",
    "BurnRateCalculator",
    "BurnRateResult",
    "BurnRateStatus",
    "CompliancePeriod",
    "MetricContract",
    "ProjectionMode",
    "SLIType",
    "SLOComplianceReport",
    "WindowProjection",
]
