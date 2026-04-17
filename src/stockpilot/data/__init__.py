"""StockPilot unified data layer."""

from stockpilot.data.manager import DataManager
from stockpilot.data.reliability.gateway import DataGateway
from stockpilot.data.runtime import (
    build_default_data_gateway,
    build_default_data_manager,
)

__all__ = [
    "DataManager",
    "DataGateway",
    "build_default_data_gateway",
    "build_default_data_manager",
]
