from preparer.redact import redact


def test_redacts_github_tokens_and_auth_headers():
    text = (
        "AUTHORIZATION: bearer gho_abcdefghijklmnopqrstuvwxyz12 "
        "and ghp_abcdefghijklmnopqrstuvwxyz12 and github_pat_abcdefghijklmnopqrst"
    )
    out = redact(text)
    assert "gho_" not in out
    assert "ghp_" not in out
    assert "github_pat_" not in out
    assert "[redacted]" in out
