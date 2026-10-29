"""pytest plugin: run exactly the tests listed in --deflake-order-file, in that order."""
import pytest


def pytest_addoption(parser):
    parser.addoption("--deflake-order-file", default=None,
                     help="File with one test node ID per line, in the order to run them.")


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session, config, items):
    path = config.getoption("deflake_order_file")
    if not path:
        return
    with open(path, encoding="utf-8") as f:
        wanted = [line.strip() for line in f if line.strip()]
    by_id = {item.nodeid: item for item in items}
    missing = [w for w in wanted if w not in by_id]
    if missing:
        raise pytest.UsageError(f"tests in the requested order were not collected: {missing[:5]}")
    wanted_set = set(wanted)
    config.hook.pytest_deselected(items=[i for i in items if i.nodeid not in wanted_set])
    items[:] = [by_id[w] for w in wanted]
