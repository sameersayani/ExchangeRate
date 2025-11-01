from pydantic import BaseModel, Field
from typing import Optional, Dict, List
from datetime import datetime

class ExchangeRateRequest(BaseModel):
    base_currency: str = Field(..., min_length=3, max_length=3, description="Base currency code (3 letters)")
    target_currency: str = Field(..., min_length=3, max_length=3, description="Target currency code (3 letters)")
    amount: Optional[float] = Field(1.0, ge=0, description="Amount to convert")

class ExchangeRateResponse(BaseModel):
    base_currency: str
    target_currency: str
    exchange_rate: float
    amount: float
    converted_amount: float
    last_updated: datetime

class HistoricalRateRequest(BaseModel):
    base_currency: str = Field(..., min_length=3, max_length=3)
    target_currency: str = Field(..., min_length=3, max_length=3)
    date: str = Field(..., description="Date in YYYY-MM-DD format")

class HistoricalRateResponse(BaseModel):
    base_currency: str
    target_currency: str
    exchange_rate: float
    date: str
    last_updated: datetime

class CurrencyListResponse(BaseModel):
    currencies: Dict[str, str]
    count: int

class BulkConversionRequest(BaseModel):
    base_currency: str = Field(..., min_length=3, max_length=3)
    conversions: List[Dict[str, float]] = Field(..., description="List of {currency: amount} pairs")

class BulkConversionResponse(BaseModel):
    base_currency: str
    conversions: Dict[str, float]
    timestamp: datetime

class APIError(BaseModel):
    detail: str
    error_code: str