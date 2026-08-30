from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class MarketDataSource(ABC):
    """A replaceable provider of canonical, ascending daily market data."""

    @abstractmethod
    def get_daily(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        raise NotImplementedError
