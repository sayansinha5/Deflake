import pytest

from shop.cart import Cart, Product
from shop.orders import OrderService

LAMP = Product("LP-2", "Desk lamp", 40.0, "garden")


def _cart(qty: int = 1) -> Cart:
    cart = Cart()
    cart.add(LAMP, qty)
    return cart


def test_order_ids_are_unique():
    service = OrderService()
    first = service.place(_cart())
    second = service.place(_cart(2))
    assert first.id != second.id
    assert service.count() == 2


def test_place_order_records_total():
    service = OrderService()
    order = service.place(_cart(2))
    assert order.total == 94.4
    assert service.get(order.id) == order


def test_cancel_order():
    service = OrderService()
    order = service.place(_cart())
    assert service.cancel(order.id).status == "cancelled"


def test_empty_cart_cannot_be_ordered():
    with pytest.raises(ValueError):
        OrderService().place(Cart())


def test_get_unknown_order_raises():
    with pytest.raises(KeyError):
        OrderService().get("ORD-0")
