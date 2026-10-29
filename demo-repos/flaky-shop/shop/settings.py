import os

SUPPORTED_CURRENCIES = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}


def default_currency() -> str:
    code = os.environ.get("SHOP_CURRENCY", "USD").upper()
    return code if code in SUPPORTED_CURRENCIES else "USD"


def currency_symbol(code: str | None = None) -> str:
    return SUPPORTED_CURRENCIES[(code or default_currency()).upper()]
