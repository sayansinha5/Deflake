import os

from shop.pricing import format_price
from shop.settings import currency_symbol, default_currency


def _use_default_currency():
    os.environ.pop("SHOP_CURRENCY", None)


def test_currency_from_environment():
    os.environ["SHOP_CURRENCY"] = "EUR"
    assert default_currency() == "EUR"
    assert format_price(10) == "€10.00"


def test_format_price_defaults_to_usd():
    assert format_price(12.5) == "$12.50"


def test_default_currency_is_usd():
    _use_default_currency()
    assert default_currency() == "USD"


def test_currency_symbol_for_default():
    _use_default_currency()
    assert currency_symbol() == "$"


def test_format_large_amount_uses_grouping():
    _use_default_currency()
    assert format_price(1234567.5) == "$1,234,567.50"


def test_explicit_currency_wins():
    assert format_price(5, "GBP") == "£5.00"


def test_unsupported_currency_falls_back(monkeypatch):
    monkeypatch.setenv("SHOP_CURRENCY", "XYZ")
    assert default_currency() == "USD"
