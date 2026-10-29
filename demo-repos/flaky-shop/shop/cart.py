from dataclasses import dataclass, field

from shop.pricing import apply_discount, tax


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price: float
    category: str


@dataclass
class Cart:
    lines: dict[str, int] = field(default_factory=dict)
    products: dict[str, Product] = field(default_factory=dict)
    discount_percent: float = 0.0

    def add(self, product: Product, qty: int = 1) -> None:
        if qty <= 0:
            raise ValueError("quantity must be positive")
        self.products[product.sku] = product
        self.lines[product.sku] = self.lines.get(product.sku, 0) + qty

    def remove(self, sku: str, qty: int | None = None) -> None:
        if sku not in self.lines:
            raise KeyError(sku)
        if qty is None or qty >= self.lines[sku]:
            del self.lines[sku]
            del self.products[sku]
        else:
            self.lines[sku] -= qty

    @property
    def item_count(self) -> int:
        return sum(self.lines.values())

    def subtotal(self) -> float:
        return round(sum(self.products[s].price * q for s, q in self.lines.items()), 2)

    def total(self) -> float:
        discounted = apply_discount(self.subtotal(), self.discount_percent)
        return round(discounted + tax(discounted), 2)
