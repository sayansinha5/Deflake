from app.integrations.audit.batch import build_items


def test_batch_is_forty_items_with_controls():
    items = build_items()
    assert len(items) == 40
    controls = [item for item in items if item["is_control"]]
    assert len(controls) == 8
    assert all(item["expected_label"] == 0 for item in controls)
    assert all(item["expected_label"] == 1 for item in items if not item["is_control"])


def test_sleep_controls_and_mismatches_are_present():
    items = build_items()
    sleeps = [item for item in items if item["item_id"].startswith("control-sleep")]
    assert sleeps and all("asyncio.sleep" in item["diff"] for item in sleeps)
    mismatches = [item for item in items if item["item_id"].startswith("control-mismatch")]
    assert mismatches
    assert any("hash-order" in item["diagnosis"] for item in mismatches)


def test_model_diagnosis_overrides_the_seeded_sentence():
    items = build_items({"F1": "Custom explanation for the rate cache."})
    f1 = [item for item in items if item["item_id"].startswith("real-f1")]
    assert f1 and all(item["diagnosis"] == "Custom explanation for the rate cache." for item in f1)


def test_excerpts_stay_within_forty_lines():
    items = build_items()
    assert all(item["failure_excerpt"].count("\n") < 40 for item in items)
