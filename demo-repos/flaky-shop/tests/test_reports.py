import time

from shop.cart import Product
from shop.reports import Line, best_seller, categories, daily_sales_summary, revenue_by_category

LINES = [
    Line(Product("BK-1", "Field guide", 77.69, "books"), 1),
    Line(Product("GM-7", "Board game", 40.57, "games"), 1),
    Line(Product("GD-3", "Hose reel", 50.65, "garden"), 1),
    Line(Product("TY-9", "Kite", 170.42, "toys"), 1),
]


def test_revenue_report_total():
    assert revenue_by_category(LINES).total == 339.33


def test_revenue_report_has_row_per_category():
    rows = dict(revenue_by_category(LINES).rows)
    assert rows == {"books": 77.69, "games": 40.57, "garden": 50.65, "toys": 170.42}


def test_categories_are_unique():
    doubled = LINES + LINES
    assert sorted(categories(doubled)) == ["books", "games", "garden", "toys"]


def test_best_seller():
    lines = [Line(LINES[0].product, 2), Line(LINES[3].product, 5), Line(LINES[0].product, 1)]
    assert best_seller(lines) == "TY-9"


def test_daily_sales_summary_text():
    assert daily_sales_summary(LINES) == "4 lines, 4 items, $339.33"


def test_daily_sales_summary_is_fast():
    started = time.perf_counter()
    daily_sales_summary(LINES)
    assert time.perf_counter() - started < 0.05
