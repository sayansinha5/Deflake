# flaky-shop

**The flaky tests in this repository are seeded on purpose, for demonstrating Deflake.** They are not accidental bugs, and the "fixes" Deflake proposes here are known in advance.

`shop` is a small online-shop package (cart, pricing, inventory, orders, coupons, reports) with 47 tests. Eight tests are deliberately unreliable or broken:

| ID | Category | Test | Seeded cause |
| --- | --- | --- | --- |
| F1 | order_dependent | `tests/test_pricing.py::test_convert_eur_to_usd` | `test_promo_rate_override` writes into a module-level rate cache and never clears it |
| F2 | async_race | `tests/test_inventory.py::test_concurrent_reservations_keep_stock_consistent` | Two coroutines read-modify-write stock without a lock |
| F3 | time_dependent | `tests/test_orders.py::test_order_ids_are_unique` | Order IDs come from the wall clock in milliseconds |
| F4 | randomness | `tests/test_coupons.py::test_batch_codes_are_unique` | Two-character coupon codes; uniqueness is assumed, not enforced |
| F5 | shared_resource | `tests/test_settings.py::test_format_price_defaults_to_usd` | `test_currency_from_environment` sets `SHOP_CURRENCY` and never restores it |
| F6 | hash_order | `tests/test_reports.py::test_revenue_report_total` | The report total is summed in `set` iteration order, so float rounding varies with `PYTHONHASHSEED` |
| B1 | broken | `tests/test_pricing.py::test_tax_standard_rate` | Wrong expected tax value; fails every run |
| E1 | environment | `tests/test_reports.py::test_daily_sales_summary_is_fast` | Wall-clock budget around a call to the (simulated) exchange-rate service |

Each flaky test is designed to fail in roughly 15 to 25% of runs with random test order (`pytest-randomly`) and a random `PYTHONHASHSEED`. Network and payment latencies are simulated with `random`, so a failing run can be reproduced from its seed.

Run the suite once:

```
pip install -r requirements-test.txt
pytest
```
