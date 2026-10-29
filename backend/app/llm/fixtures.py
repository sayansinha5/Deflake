"""Canned, schema-valid answers used when AI_PROVIDER=fake."""

CLASSIFY = {
    "category": "order_dependent",
    "rationale": "A earlier test left a module-level cache populated.",
    "confidence": 0.86,
}

SEARCH_QUERY = {
    "query": "pytest module global cache pollutes later test",
    "library": "pytest",
}

DIAGNOSE = {
    "root_cause": "A previous test mutated a process-wide cache.",
    "mechanism": "The victim reads the cache and sees a leftover rate.",
    "culprit": "shop/pricing.py::_rate_cache",
    "evidence_refs": ["failing-1"],
    "category": "order_dependent",
    "fix_strategy": "Reset the cache in a fixture or stop using module state.",
    "needs_human": False,
    "confidence": 0.8,
}

PATCH = {
    "lines": [
        "--- a/shop/pricing.py",
        "+++ b/shop/pricing.py",
        "@@ -1 +1 @@",
        "-_rate_cache = {}",
        "+_rate_cache: dict = {}",
    ],
    "summary": "Stop sharing a process-wide rate cache across tests.",
}

REFERENCE_MATCH = {"matched_urls": ["https://example.test/issue"]}

BY_SCHEMA = {
    "ClassifyOut": CLASSIFY,
    "SearchQueryOut": SEARCH_QUERY,
    "DiagnoseOut": DIAGNOSE,
    "PatchOut": PATCH,
    "ReferenceMatchOut": REFERENCE_MATCH,
    "SmokeOut": {"ok": True, "one_word": "pong", "tier": "fast"},
}
