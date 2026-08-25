"""
slo-toolkit: Calculate burn rates, generate multi-window alert thresholds,
and evaluate SLO compliance for distributed systems.
"""

from .burn_rate import BurnRateCalculator
from .alert_config import AlertConfigGenerator
from .compliance import SLOComplianceReport

__version__ = "0.1.0"
__all__ = ["BurnRateCalculator", "AlertConfigGenerator", "SLOComplianceReport"]
