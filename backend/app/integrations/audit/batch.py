"""Builds a Toloka audit batch from the seeded flaky-shop fixes.

Real items pair a correct fix with a diagnosis. Control items are deliberately wrong:
a mismatched explanation, or a patch that only adds a wait. About one item in five is a control.
"""
from app.security.redact import redact

EXCERPT_LINE_LIMIT = 40

SEEDED = [
    {
        "id": "F1",
        "test_id": "tests/test_pricing.py::test_convert_eur_to_usd",
        "category": "order_dependent",
        "excerpt": (
            "AssertionError: assert 50.0 == 110.0\n"
            "The EUR rate was left at 1.0 by test_promo_rate_override, which writes\n"
            "shop.pricing._rate_cache and never clears it. The victim fails only when\n"
            "that test ran earlier in the same process."
        ),
        "diagnosis": (
            "A promotion test writes a process-wide exchange-rate cache and does not "
            "reset it, so a later conversion test sees the leftover rate."
        ),
        "diff": (
            "--- a/tests/test_pricing.py\n+++ b/tests/test_pricing.py\n"
            "@@ -8,6 +8,13 @@\n from shop.pricing import (\n"
            "+@pytest.fixture(autouse=True)\n+def _reset_rate_cache():\n"
            "+    refresh_rates()\n+    yield\n+    refresh_rates()\n+\n+\n"
            " def test_convert_eur_to_usd():\n"
        ),
    },
    {
        "id": "F2",
        "test_id": "tests/test_inventory.py::test_concurrent_reservations_keep_stock_consistent",
        "category": "async_race",
        "excerpt": (
            "AssertionError: assert 7 == 5\n"
            "Two reservations read the same stock, both slept on the simulated warehouse\n"
            "call, then both wrote their own result. One update was lost."
        ),
        "diagnosis": (
            "reserve reads stock, waits, then writes it back with no lock, so two "
            "concurrent reservations overwrite each other."
        ),
        "diff": (
            "--- a/shop/inventory.py\n+++ b/shop/inventory.py\n"
            "@@ -16,6 +16,7 @@ class Inventory:\n"
            "+        self._lock = asyncio.Lock()\n+\n"
            "     async def reserve(self, sku: str, qty: int) -> int:\n"
            "+        async with self._lock:\n"
            "         await self._warehouse_round_trip()\n"
        ),
    },
    {
        "id": "F3",
        "test_id": "tests/test_orders.py::test_order_ids_are_unique",
        "category": "time_dependent",
        "excerpt": (
            "AssertionError: assert 'ORD-1761650000000' != 'ORD-1761650000000'\n"
            "Both orders were created in the same millisecond, and the id is the wall clock."
        ),
        "diagnosis": (
            "Order ids are the wall-clock time in milliseconds, so two orders placed "
            "close together get the same id."
        ),
        "diff": (
            "--- a/shop/orders.py\n+++ b/shop/orders.py\n"
            "@@ -18,8 +18,9 @@ class OrderService:\n"
            "+        self._seq = 0\n"
            "     def place(self, cart: Cart) -> Order:\n"
            "-        order_id = f\"ORD-{int(time.time() * 1000)}\"\n"
            "+        self._seq += 1\n+        order_id = f\"ORD-{self._seq}\"\n"
        ),
    },
    {
        "id": "F4",
        "test_id": "tests/test_coupons.py::test_batch_codes_are_unique",
        "category": "randomness",
        "excerpt": (
            "AssertionError: assert 19 == 20\n"
            "generate_batch draws two characters from a 31-letter alphabet and never "
            "checks that the code was already issued."
        ),
        "diagnosis": (
            "Coupon codes are two random characters and the generator does not reject "
            "a code it has already issued, so a batch of 20 sometimes collides."
        ),
        "diff": (
            "--- a/shop/coupons.py\n+++ b/shop/coupons.py\n"
            "@@ -14,7 +14,11 @@ def generate_code() -> str:\n"
            " def generate_batch(count: int, percent: float) -> list[Coupon]:\n"
            "+    seen: set[str] = set()\n+    codes: list[str] = []\n"
            "+    while len(codes) < count:\n+        code = generate_code()\n"
            "+        if code not in seen:\n"
            "+            seen.add(code)\n+            codes.append(code)\n"
            "-    return [Coupon(generate_code(), percent) for _ in range(count)]\n"
            "+    return [Coupon(code, percent) for code in codes]\n"
        ),
    },
    {
        "id": "F5",
        "test_id": "tests/test_settings.py::test_format_price_defaults_to_usd",
        "category": "shared_resource",
        "excerpt": (
            "AssertionError: assert '€12.50' == '$12.50'\n"
            "SHOP_CURRENCY was set to EUR by an earlier test and left in the process."
        ),
        "diagnosis": (
            "A test assigns SHOP_CURRENCY in the process environment and never restores "
            "it, so later tests format prices in the wrong currency."
        ),
        "diff": (
            "--- a/tests/test_settings.py\n+++ b/tests/test_settings.py\n"
            "@@ -6,8 +6,7 @@\n"
            "-def test_currency_from_environment():\n"
            "-    os.environ[\"SHOP_CURRENCY\"] = \"EUR\"\n"
            "+def test_currency_from_environment(monkeypatch):\n"
            "+    monkeypatch.setenv(\"SHOP_CURRENCY\", \"EUR\")\n"
            "     assert default_currency() == \"EUR\"\n"
        ),
    },
    {
        "id": "F6",
        "test_id": "tests/test_reports.py::test_revenue_report_total",
        "category": "hash_order",
        "excerpt": (
            "AssertionError: assert 339.3299999999999 == 339.33\n"
            "revenue_by_category adds category totals in set iteration order, which "
            "changes with PYTHONHASHSEED, so the float sum changes."
        ),
        "diagnosis": (
            "The report total is added in set order, so the same amounts round "
            "differently when PYTHONHASHSEED changes."
        ),
        "diff": (
            "--- a/shop/reports.py\n+++ b/shop/reports.py\n"
            "@@ -22,7 +22,7 @@ def categories(lines: list[Line]) -> list[str]:\n"
            "-    return list(set(line.product.category for line in lines))\n"
            "+    return sorted(set(line.product.category for line in lines))\n"
        ),
    },
]

SLEEP_DIFF = (
    "--- a/shop/inventory.py\n+++ b/shop/inventory.py\n"
    "@@ -20,6 +20,7 @@ class Inventory:\n"
    "     async def reserve(self, sku: str, qty: int) -> int:\n"
    "+        await asyncio.sleep(2)\n"
    "         await self._warehouse_round_trip()\n"
)

MISMATCHED = (
    "The failure is a hash-order problem: sort the set before adding the totals.",
    "The coupon alphabet is too small; lengthen the random code.",
)


def clip_excerpt(text: str) -> str:
    return _clip(text)


def _clip(text: str) -> str:
    lines = redact(text).splitlines()
    if len(lines) <= EXCERPT_LINE_LIMIT:
        return "\n".join(lines)
    return "\n".join(lines[:EXCERPT_LINE_LIMIT])


def build_items(diagnoses: dict[str, str] | None = None) -> list[dict]:
    """40 items: 32 real pairs and 8 controls. diagnoses overrides the seeded explanation."""
    diagnoses = diagnoses or {}
    real: list[dict] = []
    for seed in SEEDED:
        text = diagnoses.get(seed["id"], seed["diagnosis"])
        for copy in range(5):
            real.append({
                "item_id": f"real-{seed['id'].lower()}-{copy + 1}",
                "is_control": False,
                "expected_label": 1,
                "test_id": seed["test_id"],
                "category": seed["category"],
                "failure_excerpt": _clip(seed["excerpt"]),
                "diagnosis": redact(text),
                "diff": seed["diff"],
            })
    # 30 from the six flakes. Two more real pairs reuse F1 and F3 with the same correct diff.
    for seed in (SEEDED[0], SEEDED[2]):
        real.append({
            "item_id": f"real-{seed['id'].lower()}-extra",
            "is_control": False,
            "expected_label": 1,
            "test_id": seed["test_id"],
            "category": seed["category"],
            "failure_excerpt": _clip(seed["excerpt"]),
            "diagnosis": redact(diagnoses.get(seed["id"], seed["diagnosis"])),
            "diff": seed["diff"],
        })

    controls = []
    for index, seed in enumerate(SEEDED[:4]):
        controls.append({
            "item_id": f"control-mismatch-{index + 1}",
            "is_control": True,
            "expected_label": 0,
            "test_id": seed["test_id"],
            "category": seed["category"],
            "failure_excerpt": _clip(seed["excerpt"]),
            "diagnosis": MISMATCHED[index % len(MISMATCHED)],
            "diff": seed["diff"],
        })
    for index, seed in enumerate(SEEDED[:4]):
        controls.append({
            "item_id": f"control-sleep-{index + 1}",
            "is_control": True,
            "expected_label": 0,
            "test_id": seed["test_id"],
            "category": seed["category"],
            "failure_excerpt": _clip(seed["excerpt"]),
            "diagnosis": "A two second wait lets the other task finish, so the test passes.",
            "diff": SLEEP_DIFF,
        })
    items = real + controls
    if len(items) != 40:
        raise RuntimeError(f"batch must have 40 items, got {len(items)}")
    return items
