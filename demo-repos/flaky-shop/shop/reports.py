import random
import time
from dataclasses import dataclass

from shop.cart import Product

# Typical latency of the exchange-rate service, in seconds (simulated).
RATES_SERVICE_MEAN_LATENCY = 0.03


@dataclass(frozen=True)
class Line:
    product: Product
    qty: int

    @property
    def revenue(self) -> float:
        return round(self.product.price * self.qty, 2)


@dataclass(frozen=True)
class RevenueReport:
    rows: list[tuple[str, float]]
    total: float


def categories(lines: list[Line]) -> list[str]:
    return list(set(line.product.category for line in lines))


def revenue_by_category(lines: list[Line]) -> RevenueReport:
    rows = []
    total = 0.0
    for category in categories(lines):
        revenue = round(sum(l.revenue for l in lines if l.product.category == category), 2)
        rows.append((category, revenue))
        total += revenue
    return RevenueReport(rows=rows, total=total)


def best_seller(lines: list[Line]) -> str:
    by_sku: dict[str, int] = {}
    for line in lines:
        by_sku[line.product.sku] = by_sku.get(line.product.sku, 0) + line.qty
    return max(sorted(by_sku), key=lambda sku: by_sku[sku])


def fetch_usd_rates() -> dict[str, float]:
    """Calls the exchange-rate service. The network round trip is simulated."""
    time.sleep(random.expovariate(1 / RATES_SERVICE_MEAN_LATENCY))
    return {"USD": 1.0, "EUR": 1.10, "GBP": 1.27, "INR": 0.012}


def daily_sales_summary(lines: list[Line]) -> str:
    rates = fetch_usd_rates()
    total = sum(l.revenue for l in lines) * rates["USD"]
    return f"{len(lines)} lines, {sum(l.qty for l in lines)} items, ${total:,.2f}"
