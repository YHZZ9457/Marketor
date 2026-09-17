__version__ = "0.20.0"
from .catalog import Instrument, InstrumentCatalog
from .custom_instruments import CustomInstrumentManager
from .online_custom import OnlineCustomInstrumentManager
from .comparison import MarketComparisonService, allocation_scores
from .events import EventBacktester
from .service import CSI300Service, MarketService
from .statistics import register_statistics_method, statistics_methods
from .updater import MarketDataUpdater, UpdateResult

__all__ = [
    "CSI300Service",
    "Instrument",
    "InstrumentCatalog",
    "CustomInstrumentManager",
    "OnlineCustomInstrumentManager",
    "EventBacktester",
    "MarketService",
    "MarketDataUpdater",
    "MarketComparisonService",
    "UpdateResult",
    "register_statistics_method",
    "statistics_methods",
    "allocation_scores",
]
