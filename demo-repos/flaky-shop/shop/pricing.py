from shop.settings import currency_symbol, default_currency

TAX_RATE = 0.18

DEFAULT_RATES = {"USD": 1.0, "EUR": 1.10, "GBP": 1.27, "INR": 0.012}

# Exchange rates to USD, loaded lazily from DEFAULT_RATES and kept for the process lifetime.
_rate_cache: dict[str, float] = {}


def get_rate(currency: str) -> float:
    currency = currency.upper()
    if currency not in _rate_cache:
        _rate_cache[currency] = DEFAULT_RATES[currency]
    return _rate_cache[currency]


def set_rate_override(currency: str, rate: float) -> None:
    """Used by promotions that lock a rate for a campaign."""
    if rate <= 0:
        raise ValueError("rate must be positive")
    _rate_cache[currency.upper()] = rate


def refresh_rates() -> None:
    _rate_cache.clear()


def load_rates(feed: dict[str, float]) -> None:
    refresh_rates()
    for currency, rate in feed.items():
        _rate_cache[currency.upper()] = rate


def convert_to_usd(amount: float, currency: str) -> float:
    return round(amount * get_rate(currency), 2)


def tax(amount: float) -> float:
    return round(amount * TAX_RATE, 2)


def apply_discount(amount: float, percent: float) -> float:
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    return round(amount * (100 - percent) / 100, 2)


def format_price(amount: float, currency: str | None = None) -> str:
    code = (currency or default_currency()).upper()
    return f"{currency_symbol(code)}{amount:,.2f}"
