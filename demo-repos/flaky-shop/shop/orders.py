import random
import time
from dataclasses import dataclass

from shop.cart import Cart

# Simulated payment-gateway authorisation times, in seconds.
PAYMENT_LATENCIES = (0.0, 0.003, 0.003, 0.003, 0.003)


@dataclass(frozen=True)
class Order:
    id: str
    total: float
    item_count: int
    status: str = "placed"


class OrderService:
    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}

    def _authorise_payment(self, amount: float) -> None:
        if amount <= 0:
            raise ValueError("nothing to pay for")
        time.sleep(random.choice(PAYMENT_LATENCIES))

    def place(self, cart: Cart) -> Order:
        total = cart.total()
        self._authorise_payment(total)
        order_id = f"ORD-{int(time.time() * 1000)}"
        order = Order(id=order_id, total=total, item_count=cart.item_count)
        self._orders[order_id] = order
        return order

    def get(self, order_id: str) -> Order:
        return self._orders[order_id]

    def cancel(self, order_id: str) -> Order:
        order = self._orders[order_id]
        cancelled = Order(order.id, order.total, order.item_count, status="cancelled")
        self._orders[order_id] = cancelled
        return cancelled

    def count(self) -> int:
        return len(self._orders)
