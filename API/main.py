from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
import httpx
from typing import Dict, List, Optional
import json
import os
from models import (
    ExchangeRateRequest, 
    ExchangeRateResponse,
    HistoricalRateRequest,
    HistoricalRateResponse,
    CurrencyListResponse,
    BulkConversionRequest,
    BulkConversionResponse,
    APIError
)

app = FastAPI(
    title="Exchange Rate API",
    description="A comprehensive exchange rate API with real-time and historical data",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
API_PROVIDERS = {
    "exchangerate_api": {
        "name": "ExchangeRate-API",
        "latest_url": "https://api.exchangerate-api.com/v4/latest/",
        "historical_url": "https://api.exchangerate-api.com/v4/history/",
        "requires_key": False,
        "free_tier": True
    },
    "frankfurter": {
        "name": "Frankfurter",
        "latest_url": "https://api.frankfurter.app/latest",
        "historical_url": "https://api.frankfurter.app/",
        "requires_key": False,
        "free_tier": True
    },
    "currency_api": {
        "name": "CurrencyAPI",
        "latest_url": "https://api.currencyapi.com/v3/latest",
        "historical_url": "https://api.currencyapi.com/v3/historical",
        "requires_key": True,
        "api_key": os.getenv("CURRENCY_API_KEY", "cur_live_1234567890abcdef")  # Replace with your key
    }
}

CACHE_DURATION = 300  # 5 minutes in seconds
DEFAULT_PROVIDER = "frankfurter"  # Most reliable free provider

# In-memory cache
_cache = {}
_currency_list = None
_last_currency_update = None

class ExchangeRateService:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def get_latest_rate(self, base_currency: str, target_currency: str, provider: str = DEFAULT_PROVIDER) -> Dict:
        """Get latest exchange rate from selected provider"""
        cache_key = f"latest_{base_currency}_{target_currency}_{provider}"
        
        # Check cache
        if cache_key in _cache and _cache[cache_key]['timestamp'] > datetime.now() - timedelta(seconds=CACHE_DURATION):
            return _cache[cache_key]['data']
        
        provider_config = API_PROVIDERS.get(provider)
        if not provider_config:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid provider: {provider}"
            )
        
        try:
            if provider == "exchangerate_api":
                url = f"{provider_config['latest_url']}{base_currency.upper()}"
                response = await self.client.get(url)
                data = response.json()
                
                if 'result' in data and data['result'] == 'error':
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"API error: {data.get('error', 'Unknown error')}"
                    )
                
                rate = data['rates'].get(target_currency.upper())
                if not rate:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Target currency {target_currency} not supported"
                    )
                
                result = {
                    'success': True,
                    'base': base_currency.upper(),
                    'rates': {target_currency.upper(): rate},
                    'timestamp': int(datetime.now().timestamp())
                }
                
            elif provider == "frankfurter":
                url = provider_config['latest_url']
                params = {
                    'from': base_currency.upper(),
                    'to': target_currency.upper()
                }
                response = await self.client.get(url, params=params)
                data = response.json()
                
                if 'error' in data:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"API error: {data['error']}"
                    )
                
                result = {
                    'success': True,
                    'base': data['base'],
                    'rates': data['rates'],
                    'timestamp': int(datetime.now().timestamp())
                }
                
            elif provider == "currency_api":
                url = provider_config['latest_url']
                params = {
                    'base_currency': base_currency.upper(),
                    'currencies': target_currency.upper()
                }
                if provider_config['requires_key']:
                    params['apikey'] = provider_config['api_key']
                
                response = await self.client.get(url, params=params)
                data = response.json()
                
                if 'errors' in data:
                    error_msg = next(iter(data['errors'].values()))['message']
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"API error: {error_msg}"
                    )
                
                rate = data['data'].get(target_currency.upper(), {}).get('value')
                if not rate:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Target currency {target_currency} not supported"
                    )
                
                result = {
                    'success': True,
                    'base': base_currency.upper(),
                    'rates': {target_currency.upper(): rate},
                    'timestamp': int(datetime.now().timestamp())
                }
            
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Unsupported provider"
                )
            
            # Cache the result
            _cache[cache_key] = {
                'data': result,
                'timestamp': datetime.now()
            }
            
            return result
            
        except httpx.RequestError as e:
            # Try fallback provider
            if provider != DEFAULT_PROVIDER:
                return await self.get_latest_rate(base_currency, target_currency, DEFAULT_PROVIDER)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Exchange rate service unavailable: {str(e)}"
            )
    
    async def get_historical_rate(self, base_currency: str, target_currency: str, date: str, provider: str = DEFAULT_PROVIDER) -> Dict:
        """Get historical exchange rate"""
        cache_key = f"historical_{base_currency}_{target_currency}_{date}_{provider}"
        
        # Check cache
        if cache_key in _cache and _cache[cache_key]['timestamp'] > datetime.now() - timedelta(seconds=CACHE_DURATION):
            return _cache[cache_key]['data']
        
        # Validate date format
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format. Use YYYY-MM-DD"
            )
        
        provider_config = API_PROVIDERS.get(provider)
        if not provider_config:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid provider: {provider}"
            )
        
        try:
            if provider == "frankfurter":
                url = f"{provider_config['historical_url']}{date}"
                params = {
                    'from': base_currency.upper(),
                    'to': target_currency.upper()
                }
                response = await self.client.get(url, params=params)
                data = response.json()
                
                if 'error' in data:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"API error: {data['error']}"
                    )
                
                result = {
                    'success': True,
                    'base': data['base'],
                    'rates': data['rates'],
                    'date': date
                }
                
            elif provider == "currency_api":
                url = provider_config['historical_url']
                params = {
                    'base_currency': base_currency.upper(),
                    'currencies': target_currency.upper(),
                    'date': date
                }
                if provider_config['requires_key']:
                    params['apikey'] = provider_config['api_key']
                
                response = await self.client.get(url, params=params)
                data = response.json()
                
                if 'errors' in data:
                    error_msg = next(iter(data['errors'].values()))['message']
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"API error: {error_msg}"
                    )
                
                rate = data['data'].get(target_currency.upper(), {}).get('value')
                if not rate:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Target currency {target_currency} not supported for date {date}"
                    )
                
                result = {
                    'success': True,
                    'base': base_currency.upper(),
                    'rates': {target_currency.upper(): rate},
                    'date': date
                }
            
            else:
                # For providers without historical support, use latest as fallback
                return await self.get_latest_rate(base_currency, target_currency, provider)
            
            # Cache the result
            _cache[cache_key] = {
                'data': result,
                'timestamp': datetime.now()
            }
            
            return result
            
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Historical rate service unavailable: {str(e)}"
            )
    
    async def get_currency_list(self) -> Dict:
        """Get list of supported currencies"""
        global _currency_list, _last_currency_update
        
        # Update currency list once per day
        if _currency_list and _last_currency_update and _last_currency_update.date() == datetime.now().date():
            return _currency_list
        
        cache_key = "currency_list"
        
        # Check cache
        if cache_key in _cache and _cache[cache_key]['timestamp'] > datetime.now() - timedelta(hours=24):
            _currency_list = _cache[cache_key]['data']
            _last_currency_update = _cache[cache_key]['timestamp']
            return _currency_list
        
        # Common currencies with their names
        common_currencies = {
            "USD": "United States Dollar",
            "EUR": "Euro",
            "GBP": "British Pound Sterling",
            "JPY": "Japanese Yen",
            "CAD": "Canadian Dollar",
            "AUD": "Australian Dollar",
            "CHF": "Swiss Franc",
            "CNY": "Chinese Yuan",
            "INR": "Indian Rupee",
            "BRL": "Brazilian Real",
            "RUB": "Russian Ruble",
            "MXN": "Mexican Peso",
            "SGD": "Singapore Dollar",
            "HKD": "Hong Kong Dollar",
            "NZD": "New Zealand Dollar",
            "KRW": "South Korean Won",
            "TRY": "Turkish Lira",
            "ZAR": "South African Rand",
            "SEK": "Swedish Krona",
            "NOK": "Norwegian Krone",
            "DKK": "Danish Krone",
            "PLN": "Polish Zloty",
            "THB": "Thai Baht",
            "IDR": "Indonesian Rupiah",
            "MYR": "Malaysian Ringgit",
            "PHP": "Philippine Peso",
            "CZK": "Czech Koruna",
            "HUF": "Hungarian Forint",
        }
        
        _currency_list = common_currencies
        _last_currency_update = datetime.now()
        
        # Cache the result
        _cache[cache_key] = {
            'data': _currency_list,
            'timestamp': _last_currency_update
        }
        
        return _currency_list

# Initialize service
exchange_service = ExchangeRateService()

@app.get("/", tags=["Health"])
async def root():
    """Health check endpoint"""
    return {
        "message": "Exchange Rate API is running",
        "version": "1.0.0",
        "timestamp": datetime.now(),
        "providers": list(API_PROVIDERS.keys())
    }

@app.get(
    "/rates/latest",
    response_model=ExchangeRateResponse,
    responses={400: {"model": APIError}, 503: {"model": APIError}},
    tags=["Exchange Rates"]
)
async def get_latest_rate(
    base_currency: str = Query(..., description="Base currency code (3 letters)"),
    target_currency: str = Query(..., description="Target currency code (3 letters)"),
    amount: float = Query(1.0, ge=0, description="Amount to convert"),
    provider: str = Query(DEFAULT_PROVIDER, description="API provider to use")
):
    """
    Get the latest exchange rate between two currencies
    """
    data = await exchange_service.get_latest_rate(base_currency, target_currency, provider)
    
    rate = data['rates'].get(target_currency.upper())
    if not rate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Target currency {target_currency} not found in response"
        )
    
    return ExchangeRateResponse(
        base_currency=base_currency.upper(),
        target_currency=target_currency.upper(),
        exchange_rate=rate,
        amount=amount,
        converted_amount=amount * rate,
        last_updated=datetime.fromtimestamp(data.get('timestamp', datetime.now().timestamp()))
    )

@app.post(
    "/rates/convert",
    response_model=ExchangeRateResponse,
    responses={400: {"model": APIError}, 503: {"model": APIError}},
    tags=["Exchange Rates"]
)
async def convert_currency(
    request: ExchangeRateRequest,
    provider: str = Query(DEFAULT_PROVIDER, description="API provider to use")
):
    """
    Convert amount from one currency to another
    """
    data = await exchange_service.get_latest_rate(request.base_currency, request.target_currency, provider)
    
    rate = data['rates'].get(request.target_currency.upper())
    if not rate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Target currency {request.target_currency} not found"
        )
    
    return ExchangeRateResponse(
        base_currency=request.base_currency.upper(),
        target_currency=request.target_currency.upper(),
        exchange_rate=rate,
        amount=request.amount,
        converted_amount=request.amount * rate,
        last_updated=datetime.fromtimestamp(data.get('timestamp', datetime.now().timestamp()))
    )

@app.get(
    "/rates/historical",
    response_model=HistoricalRateResponse,
    responses={400: {"model": APIError}, 503: {"model": APIError}},
    tags=["Historical Rates"]
)
async def get_historical_rate(
    base_currency: str = Query(..., description="Base currency code"),
    target_currency: str = Query(..., description="Target currency code"),
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    provider: str = Query(DEFAULT_PROVIDER, description="API provider to use")
):
    """
    Get historical exchange rate for a specific date
    """
    data = await exchange_service.get_historical_rate(base_currency, target_currency, date, provider)
    
    rate = data['rates'].get(target_currency.upper())
    if not rate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Target currency {target_currency} not found for the specified date"
        )
    
    return HistoricalRateResponse(
        base_currency=base_currency.upper(),
        target_currency=target_currency.upper(),
        exchange_rate=rate,
        date=date,
        last_updated=datetime.now()
    )

@app.get(
    "/currencies",
    response_model=CurrencyListResponse,
    responses={503: {"model": APIError}},
    tags=["Currencies"]
)
async def get_currencies():
    """
    Get list of all supported currencies
    """
    currencies = await exchange_service.get_currency_list()
    
    return CurrencyListResponse(
        currencies=currencies,
        count=len(currencies)
    )

@app.post(
    "/rates/bulk-convert",
    response_model=BulkConversionResponse,
    responses={400: {"model": APIError}, 503: {"model": APIError}},
    tags=["Exchange Rates"]
)
async def bulk_convert_currency(
    request: BulkConversionRequest,
    provider: str = Query(DEFAULT_PROVIDER, description="API provider to use")
):
    """
    Convert amounts to multiple currencies at once
    """
    if not request.conversions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No conversions provided"
        )
    
    # Get all unique target currencies
    target_currencies = set()
    for conversion in request.conversions:
        target_currencies.update(conversion.keys())
    
    conversions_result = {}
    
    # Get rates for each target currency
    for currency in target_currencies:
        try:
            data = await exchange_service.get_latest_rate(request.base_currency, currency, provider)
            rate = data['rates'].get(currency.upper())
            if rate:
                # Apply conversion for all amounts for this currency
                for conversion in request.conversions:
                    if currency in conversion:
                        conversions_result[f"{currency.upper()}_{conversion[currency]}"] = conversion[currency] * rate
        except Exception:
            # Skip failed conversions
            continue
    
    return BulkConversionResponse(
        base_currency=request.base_currency.upper(),
        conversions=conversions_result,
        timestamp=datetime.now()
    )

@app.get("/rates/compare", tags=["Exchange Rates"])
async def compare_currencies(
    base_currency: str = Query(..., description="Base currency code"),
    target_currencies: str = Query(..., description="Comma-separated list of target currencies"),
    provider: str = Query(DEFAULT_PROVIDER, description="API provider to use")
):
    """
    Compare exchange rates for multiple currencies
    """
    currencies = [currency.strip().upper() for currency in target_currencies.split(',')]
    
    comparison_results = {}
    
    for currency in currencies:
        try:
            data = await exchange_service.get_latest_rate(base_currency, currency, provider)
            rate = data['rates'].get(currency)
            if rate:
                comparison_results[currency] = rate
        except Exception as e:
            comparison_results[currency] = f"Error: {str(e)}"
    
    return {
        "base_currency": base_currency.upper(),
        "rates": comparison_results,
        "timestamp": datetime.now(),
        "compared_currencies": currencies,
        "provider": provider
    }

@app.get("/providers", tags=["Health"])
async def get_providers():
    """
    Get list of available API providers
    """
    providers_info = {}
    for key, config in API_PROVIDERS.items():
        providers_info[key] = {
            "name": config["name"],
            "requires_key": config["requires_key"],
            "free_tier": config.get("free_tier", False)
        }
    
    return {
        "providers": providers_info,
        "default_provider": DEFAULT_PROVIDER
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )