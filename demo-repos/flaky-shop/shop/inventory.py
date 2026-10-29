import asyncio
import random

# Simulated round-trip times to the warehouse service, in seconds.
WAREHOUSE_LATENCIES = (0.0, 0.003, 0.006, 0.009, 0.012)
WRITE_LATENCY = 0.001


class OutOfStock(Exception):
    pass


class Inventory:
    def __init__(self, stock: dict[str, int] | None = None) -> None:
        self._stock: dict[str, int] = dict(stock or {})

    def available(self, sku: str) -> int:
        return self._stock.get(sku, 0)

    def restock(self, sku: str, qty: int) -> None:
        if qty <= 0:
            raise ValueError("quantity must be positive")
        self._stock[sku] = self._stock.get(sku, 0) + qty

    async def _warehouse_round_trip(self) -> None:
        await asyncio.sleep(random.choice(WAREHOUSE_LATENCIES))

    async def reserve(self, sku: str, qty: int) -> int:
        await self._warehouse_round_trip()
        current = self._stock.get(sku, 0)
        if current < qty:
            raise OutOfStock(sku)
        await asyncio.sleep(WRITE_LATENCY)
        self._stock[sku] = current - qty
        return self._stock[sku]
