import pytest

from shop.pricing import (
    apply_discount,
    convert_to_usd,
    get_rate,
    load_rates,
    refresh_rates,
    set_rate_override,
    tax,
)


def test_convert_eur_to_usd():
    assert convert_to_usd(100.0, "EUR") == 110.0


def test_promo_rate_override():
    set_rate_override("EUR", 1.0)
    assert convert_to_usd(50.0, "EUR") == 50.0


def test_refresh_rates_restores_defaults():
    set_rate_override("GBP", 2.0)
    refresh_rates()
    assert get_rate("GBP") == 1.27


def test_load_rates_replaces_cache():
    load_rates({"INR": 0.013})
    assert get_rate("INR") == 0.013


def test_load_rates_accepts_lowercase_codes():
    load_rates({"inr": 0.012})
    assert get_rate("INR") == 0.012


def test_convert_usd_is_identity():
    assert convert_to_usd(19.99, "USD") == 19.99


def test_override_rejects_non_positive_rate():
    with pytest.raises(ValueError):
        set_rate_override("EUR", 0)


def test_unknown_currency_raises():
    with pytest.raises(KeyError):
        get_rate("JPY")


def test_tax_standard_rate():
    assert tax(100.0) == 17.0


def test_apply_discount():
    assert apply_discount(200.0, 15) == 170.0


def test_apply_discount_rejects_out_of_range():
    with pytest.raises(ValueError):
        apply_discount(10.0, 120)
