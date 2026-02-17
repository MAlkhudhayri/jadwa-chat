"""Pydantic schemas for time series API."""

from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime


class SeriesCatalogOut(BaseModel):
    series_id: str
    name: str
    domain: str
    source: str
    unit: Optional[str] = None
    frequency: str = "monthly"
    source_url: Optional[str] = None
    description: Optional[str] = None

    class Config:
        from_attributes = True


class ObservationOut(BaseModel):
    series_id: str
    date: date
    value: Optional[float] = None

    class Config:
        from_attributes = True


class LatestResult(BaseModel):
    series_id: str
    series_name: str
    date: date
    value: Optional[float]
    unit: Optional[str]
    is_forecast: bool = False
    staleness_days: int = 0
    source_url: Optional[str] = None


class ChangeResult(BaseModel):
    series_id: str
    series_name: str
    method: str  # MoM, YoY, QoQ
    current_date: date
    current_value: Optional[float]
    previous_date: date
    previous_value: Optional[float]
    change_absolute: Optional[float]
    change_percent: Optional[float]
    unit: Optional[str]


class SeriesDataResult(BaseModel):
    series_id: str
    series_name: str
    unit: Optional[str]
    observations: List[ObservationOut]
    count: int


class AnalyticsResponse(BaseModel):
    tool: str
    result: dict
    series_used: List[str]
    staleness_days: Optional[int] = None
    source_url: Optional[str] = None

