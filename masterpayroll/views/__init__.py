"""Viste web. Un solo blueprint ("main") diviso per area come i menu di Odoo."""
from . import academy, config, hr, payslips
from .common import bp

__all__ = ["bp", "academy", "config", "hr", "payslips"]
