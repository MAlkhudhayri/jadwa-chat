"""Base connector for data ingestion."""

from dataclasses import dataclass
from datetime import date
from typing import Optional, List


@dataclass
class ParsedObservation:
    series_id: str
    date: date
    value: Optional[float] = None
    as_of_date: Optional[date] = None

