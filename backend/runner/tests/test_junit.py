from runner.junit import parse_junit, truncate

SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="6">
  <testcase classname="tests.test_a" name="test_ok" file="tests/test_a.py" line="1" time="0.010"/>
  <testcase classname="tests.test_a" name="test_bad" file="tests/test_a.py" line="5" time="0.002">
    <failure message="AssertionError: assert 1 == 2">def test_bad():
&gt;       assert 1 == 2
E       AssertionError</failure>
  </testcase>
  <testcase classname="tests.test_a" name="test_fixture" file="tests/test_a.py" line="9" time="0">
    <error message="failed on setup with &quot;RuntimeError&quot;">RuntimeError: boom</error>
  </testcase>
  <testcase classname="tests.test_a" name="test_later" file="tests/test_a.py" line="12" time="0">
    <skipped type="pytest.skip" message="not today">skip reason</skipped>
  </testcase>
  <testcase classname="tests.test_a" name="test_hang" file="tests/test_a.py" line="15" time="2.004">
    <failure message="Failed: Timeout (&gt;2.0s) from pytest-timeout.">+++ Timeout +++</failure>
  </testcase>
  <testcase classname="tests.test_b.TestCart" name="test_add[two-items]" file="tests/test_b.py"
            line="3" time="0.001"/>
</testsuite></testsuites>"""

COLLECTION_ERROR = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" tests="1">
  <testcase classname="" name="tests.test_broken" time="0.000">
    <error message="collection failure">ImportError: No module named 'nope'</error>
  </testcase>
</testsuite></testsuites>"""


def test_outcomes_and_node_ids():
    report = parse_junit(SAMPLE)
    by_id = {r.test_id: r for r in report.results}
    assert by_id["tests/test_a.py::test_ok"].outcome == "passed"
    assert by_id["tests/test_a.py::test_ok"].duration_ms == 10
    assert by_id["tests/test_a.py::test_bad"].outcome == "failed"
    assert "assert 1 == 2" in by_id["tests/test_a.py::test_bad"].traceback
    assert by_id["tests/test_a.py::test_fixture"].outcome == "error"
    assert by_id["tests/test_a.py::test_later"].outcome == "skipped"
    assert by_id["tests/test_a.py::test_hang"].outcome == "timeout"
    assert by_id["tests/test_b.py::TestCart::test_add[two-items]"].outcome == "passed"
    assert report.collection_errors == []


def test_results_keep_execution_order():
    ids = [r.test_id for r in parse_junit(SAMPLE).results]
    assert ids[0] == "tests/test_a.py::test_ok"
    assert ids[-1] == "tests/test_b.py::TestCart::test_add[two-items]"


def test_collection_error_is_reported_separately():
    report = parse_junit(COLLECTION_ERROR)
    assert report.results == []
    assert "No module named 'nope'" in report.collection_errors[0]


def test_truncate_keeps_head_and_tail():
    text = "A" * 3000 + "B" * 3000
    out = truncate(text, limit=1000)
    assert out.startswith("A" * 500) and out.endswith("B" * 500)
    assert "5000 characters cut" in out


def test_entity_expansion_is_refused():
    import pytest
    from defusedxml import EntitiesForbidden

    bomb = """<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>"""
    with pytest.raises(EntitiesForbidden):
        parse_junit(bomb)
