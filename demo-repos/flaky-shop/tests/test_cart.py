import pytest

from shop.cart import Cart, Product

BOOK = Product("BK-1", "Field guide", 25.0, "books")
GAME = Product("GM-7", "Board game", 50.0, "games")


def test_add_accumulates_quantity():
    cart = Cart()
    cart.add(BOOK)
    cart.add(BOOK, 2)
    assert cart.lines["BK-1"] == 3


def test_add_rejects_non_positive_quantity():
    with pytest.raises(ValueError):
        Cart().add(BOOK, 0)


def test_remove_partial_quantity():
    cart = Cart()
    cart.add(GAME, 3)
    cart.remove("GM-7", 1)
    assert cart.lines["GM-7"] == 2


def test_remove_whole_line():
    cart = Cart()
    cart.add(GAME)
    cart.remove("GM-7")
    assert cart.item_count == 0


def test_subtotal():
    cart = Cart()
    cart.add(BOOK, 2)
    cart.add(GAME)
    assert cart.subtotal() == 100.0


def test_total_includes_tax():
    cart = Cart()
    cart.add(GAME, 2)
    assert cart.total() == 118.0


def test_checkout_applies_discount():
    cart = Cart(discount_percent=10)
    cart.add(BOOK, 2)
    cart.add(GAME)
    assert cart.total() == 106.2
