import asyncio

import pytest

from shop.inventory import Inventory, OutOfStock


def test_concurrent_reservations_keep_stock_consistent():
    inventory = Inventory({"BK-1": 10})

    async def checkout_two_customers():
        await asyncio.gather(inventory.reserve("BK-1", 2), inventory.reserve("BK-1", 3))

    asyncio.run(checkout_two_customers())
    assert inventory.available("BK-1") == 5


def test_reserve_reduces_stock():
    inventory = Inventory({"GM-7": 4})
    assert asyncio.run(inventory.reserve("GM-7", 3)) == 1


def test_reserve_more_than_available_raises():
    inventory = Inventory({"GM-7": 1})
    with pytest.raises(OutOfStock):
        asyncio.run(inventory.reserve("GM-7", 2))


def test_restock_adds():
    inventory = Inventory()
    inventory.restock("BK-1", 5)
    inventory.restock("BK-1", 2)
    assert inventory.available("BK-1") == 7


def test_restock_rejects_non_positive():
    with pytest.raises(ValueError):
        Inventory().restock("BK-1", 0)
