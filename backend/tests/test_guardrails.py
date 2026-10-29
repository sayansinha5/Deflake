"""One fixture diff for each guardrail, plus a change that is allowed."""
import difflib

from app.services.guardrails import check_patch

EDITABLE = ["shop/**", "tests/**"]


def _diff(path: str, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    ))


def _rules(path: str, before: str, after: str) -> set[str]:
    diff = _diff(path, before, after)
    return {item.rule for item in check_patch(diff, {path: before}, EDITABLE)}


def test_g1_rejects_a_new_sleep_but_not_one_already_there():
    before = "def reserve():\n    return 1\n"
    after = "import time\n\ndef reserve():\n    time.sleep(1)\n    return 1\n"
    assert "G1" in _rules("shop/inventory.py", before, after)

    existing = (
        "import asyncio\n\nasync def reserve():\n"
        "    await asyncio.sleep(0.01)\n    return 1\n"
    )
    locked = (
        "import asyncio\n\n_lock = asyncio.Lock()\n\n"
        "async def reserve():\n    async with _lock:\n"
        "        await asyncio.sleep(0.01)\n        return 1\n"
    )
    assert _rules("shop/inventory.py", existing, locked) == set()


def test_g2_rejects_a_retry_decorator_and_an_assertion_loop():
    path = "tests/test_inventory.py"
    before = "def test_stock():\n    assert reserve() == 1\n"
    marked = (
        "import pytest\n\n@pytest.mark.flaky(reruns=3)\n"
        "def test_stock():\n    assert reserve() == 1\n"
    )
    assert "G2" in _rules(path, before, marked)

    looped = "def test_stock():\n    for _ in range(5):\n        assert reserve() == 1\n"
    assert "G2" in _rules(path, before, looped)


def test_g3_rejects_a_deleted_test_and_a_skip():
    path = "tests/test_orders.py"
    before = "def test_keep():\n    assert True\n\ndef test_drop():\n    assert True\n"
    after = "def test_keep():\n    assert True\n"
    assert "G3" in _rules(path, before, after)

    skipped = (
        "import pytest\n\n@pytest.mark.skip\n"
        "def test_keep():\n    assert True\n\ndef test_drop():\n    assert True\n"
    )
    assert "G3" in _rules(path, before, skipped)


def test_g4_rejects_a_weaker_assertion():
    path = "tests/test_pricing.py"
    before = "def test_rate():\n    assert convert(1) == 1.1\n"
    after = "def test_rate():\n    assert True\n"
    assert "G4" in _rules(path, before, after)

    wide = "def test_rate():\n    assert convert(1) == pytest.approx(1.1, rel=1e-6)\n"
    wider = "def test_rate():\n    assert convert(1) == pytest.approx(1.1, rel=1e-2)\n"
    assert "G4" in _rules(path, wide, wider)


def test_g5_rejects_a_timeout_raised_more_than_twice():
    path = "tests/test_reports.py"
    before = "def test_report():\n    assert run(timeout=1) == 1\n"
    after = "def test_report():\n    assert run(timeout=3) == 1\n"
    assert "G5" in _rules(path, before, after)

    fresh = "def test_report():\n    assert run() == 1\n"
    added = "def test_report():\n    assert run(timeout=5) == 1\n"
    assert "G5" not in _rules(path, fresh, added)


def test_g6_rejects_paths_outside_the_allowlist_and_config_files():
    assert "G6" in _rules("README.md", "old\n", "new\n")
    config = "--- a/pytest.ini\n+++ b/pytest.ini\n@@ -0,0 +1 @@\n+[pytest]\n"
    rules = {item.rule for item in check_patch(config, {}, EDITABLE)}
    assert "G6" in rules


def test_g7_rejects_too_many_files_or_lines():
    parts = [_diff(f"shop/m{i}.py", "x = 1\n", "x = 2\n") for i in range(4)]
    rules = {item.rule for item in check_patch("".join(parts), {}, EDITABLE)}
    assert "G7" in rules

    before = "x = 1\n"
    after = "".join(f"x = {i}\n" for i in range(90))
    assert "G7" in _rules("shop/big.py", before, after)


def test_g8_rejects_a_dangerous_import():
    before = "def reserve():\n    return 1\n"
    after = "import subprocess\n\ndef reserve():\n    return 1\n"
    assert "G8" in _rules("shop/inventory.py", before, after)


def test_g9_rejects_a_pinned_seed_and_disabled_random_order():
    before = "import random\n\ndef reserve():\n    return random.random()\n"
    after = "import random\n\ndef reserve():\n    random.seed(1)\n    return random.random()\n"
    assert "G9" in _rules("shop/orders.py", before, after)

    path = "tests/test_orders.py"
    original = "def test_a():\n    assert True\n"
    pinned = "def test_a():\n    # no:randomly\n    assert True\n"
    assert "G9" in _rules(path, original, pinned)


def test_a_lock_is_accepted():
    before = (
        "import asyncio\n\nasync def reserve():\n"
        "    stock = read()\n    await write(stock - 1)\n"
    )
    after = (
        "import asyncio\n\n_lock = asyncio.Lock()\n\n"
        "async def reserve():\n    async with _lock:\n"
        "        stock = read()\n        await write(stock - 1)\n"
    )
    assert check_patch(
        _diff("shop/inventory.py", before, after),
        {"shop/inventory.py": before},
        EDITABLE,
    ) == []


def test_g4_rejects_replacing_an_exact_compare_with_approx():
    path = "tests/test_reports.py"
    before = "def test_total():\n    assert total == 339.33\n"
    after = "def test_total():\n    assert total == pytest.approx(339.33)\n"
    assert "G4" in _rules(path, before, after)


def test_g5_rejects_a_comparison_timeout_raised_more_than_twice():
    path = "tests/test_reports.py"
    before = "def test_fast():\n    assert elapsed < 0.05\n"
    after = "def test_fast():\n    assert elapsed < 0.5\n"
    assert "G5" in _rules(path, before, after)
    modest = "def test_fast():\n    assert elapsed < 0.09\n"
    assert "G5" not in _rules(path, before, modest)


def test_html_breaks_are_read_as_newlines():
    original = "def generate():\n    return [1]\n"
    raw = (
        "-- a/shop/coupons.py<br/>+++ b/shop/coupons.py<br/>"
        "@@ -1,2 +1,2 @@<br/> def generate():<br/>-    return [1]<br/>"
        "+    return [2]<br/>"
    )
    assert check_patch(raw, {"shop/coupons.py": original}, EDITABLE) == []


def test_an_insertion_still_applies_when_blank_lines_differ():
    original = (
        "from shop.pricing import (\n"
        "    tax,\n"
        ")\n"
        "\n"
        "\n"
        "def test_convert():\n"
        "    assert True\n"
    )
    raw = (
        "--- a/tests/test_pricing.py\n"
        "+++ b/tests/test_pricing.py\n"
        "@@\n"
        " from shop.pricing import (\n"
        "     tax,\n"
        " )\n"
        "+\n"
        "+def reset():\n"
        "+    pass\n"
        " \n"
        " def test_convert():\n"
        "     assert True\n"
    )
    assert check_patch(raw, {"tests/test_pricing.py": original}, EDITABLE) == []


def test_a_bare_filename_uses_the_shown_file_and_the_deleted_lines():
    original = "def generate_batch(count, percent):\n    return [1]\n"
    raw = (
        "--- a/coupons.py\n+++ b/coupons.py\n@@\n"
        "-    return [1]\n"
        "+    return list(range(count))\n"
        " def missing():\n"
        "     pass\n"
    )
    assert check_patch(raw, {"shop/coupons.py": original}, EDITABLE) == []


def test_a_hunk_without_line_numbers_still_applies():
    original = (
        "class Inventory:\n"
        "    def __init__(self):\n"
        "        self._stock = {}\n"
        "\n"
        "    def available(self):\n"
        "        return 0\n"
    )
    raw = (
        "--- a/shop/inventory.py\n"
        "+++ b/shop/inventory.py\n"
        "@@\n"
        "     def __init__(self):\n"
        "         self._stock = {}\n"
        "+        self._lock = Lock()\n"
        " \n"
        "     def available(self):\n"
        "         return 0\n"
    )
    assert check_patch(raw, {"shop/inventory.py": original}, EDITABLE) == []


def test_a_smashed_diff_is_not_accepted_unchanged():
    original = "class Inventory:\n    def __init__(self):\n        pass\n"
    smashed = "--- a/shop/inventory.py+++ b/shop/inventory.py@@    def __init__(self): pass"
    found = check_patch(smashed, {"shop/inventory.py": original}, EDITABLE)
    assert found


def test_a_diff_that_does_not_apply_is_rejected():
    original = "from shop.settings import currency_symbol\n"
    bad = (
        "--- a/shop/pricing.py\n+++ b/shop/pricing.py\n"
        "@@ -1 +1 @@\n-_rate_cache = {}\n+_rates = {}\n"
    )
    found = check_patch(bad, {"shop/pricing.py": original}, EDITABLE)
    assert "apply" in {item.rule for item in found}
