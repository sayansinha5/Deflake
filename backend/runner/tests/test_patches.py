import pytest

from runner.patches import PatchRejected, apply_patch, check_paths

GOOD = """diff --git a/shop/x.py b/shop/x.py
--- a/shop/x.py
+++ b/shop/x.py
@@ -1 +1 @@
-A = 1
+A = 2
"""


def test_normal_paths_accepted():
    assert check_paths(GOOD) == {"shop/x.py"}


@pytest.mark.parametrize("patch", [
    GOOD.replace("shop/x.py", "../outside.py"),
    GOOD.replace("a/shop/x.py", "/etc/passwd").replace("b/shop/x.py", "/etc/passwd"),
    GOOD.replace("shop/x.py", "shop/../../escape.py"),
    "diff --git a/shop/x.py b/shop/y.py\nrename from shop/x.py\nrename to ../../y.py\n",
    GOOD.replace("shop/x.py", "shop\\..\\..\\x.py"),
])
def test_traversal_rejected(patch):
    with pytest.raises(PatchRejected):
        check_paths(patch)


def test_binary_patch_rejected():
    with pytest.raises(PatchRejected):
        check_paths(GOOD + "GIT binary patch\nliteral 0\n")


def test_empty_patch_rejected():
    with pytest.raises(PatchRejected):
        check_paths("just text, no diff headers\n")


def test_mid_file_hunk_without_trailing_context_applies(tmp_path):
    repo = tmp_path / "repo"
    (repo / "shop").mkdir(parents=True)
    target = repo / "shop" / "x.py"
    target.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
    patch = (
        "--- a/shop/x.py\n+++ b/shop/x.py\n"
        "@@ -2,1 +2,1 @@\n"
        "-two\n"
        "+TWO\n"
    )
    apply_patch(patch, repo)
    assert target.read_text(encoding="utf-8") == "one\nTWO\nthree\nfour\nfive\n"


def test_trailing_context_stops_before_the_next_hunk(tmp_path):
    repo = tmp_path / "repo"
    (repo / "shop").mkdir(parents=True)
    target = repo / "shop" / "x.py"
    target.write_text("a\nb\nc\nd\ne\nf\n", encoding="utf-8")
    patch = (
        "--- a/shop/x.py\n+++ b/shop/x.py\n"
        "@@ -2,1 +2,1 @@\n"
        "-b\n"
        "+B\n"
        "@@ -5,1 +5,1 @@\n"
        "-e\n"
        "+E\n"
    )
    apply_patch(patch, repo)
    assert target.read_text(encoding="utf-8") == "a\nB\nc\nd\nE\nf\n"


def test_unmatched_hunk_is_still_rejected(tmp_path):
    repo = tmp_path / "repo"
    (repo / "shop").mkdir(parents=True)
    (repo / "shop" / "x.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    patch = "--- a/shop/x.py\n+++ b/shop/x.py\n@@ -2,1 +2,1 @@\n-missing\n+TWO\n"
    with pytest.raises(PatchRejected):
        apply_patch(patch, repo)
