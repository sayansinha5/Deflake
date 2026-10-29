import pytest

from shop.coupons import ALPHABET, generate_batch, generate_code, redeem


def test_batch_codes_are_unique():
    batch = generate_batch(20, percent=10)
    assert len({coupon.code for coupon in batch}) == 20


def test_code_uses_unambiguous_alphabet():
    code = generate_code()
    assert len(code) == 2
    assert set(code) <= set(ALPHABET)
    assert not set(code) & set("0O1IL")


def test_redeem_finds_coupon():
    batch = generate_batch(3, percent=15)
    assert redeem(batch, batch[1].code).code == batch[1].code


def test_redeem_is_case_insensitive():
    batch = generate_batch(1, percent=5)
    assert redeem(batch, batch[0].code.lower()).percent == 5


def test_redeem_unknown_raises():
    with pytest.raises(KeyError):
        redeem([], "ZZ")


def test_batch_rejects_bad_percent():
    with pytest.raises(ValueError):
        generate_batch(5, percent=0)
