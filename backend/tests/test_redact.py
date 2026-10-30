from app.security.redact import REDACTED, REDACTED_EMAIL, REDACTED_PATH, redact, redact_obj

CLEAN = "A test failed because the cart total was 12.50 after tax."


def test_text_without_secrets_is_unchanged():
    assert redact(CLEAN) == CLEAN


def test_openai_style_key():
    assert REDACTED in redact("key=sk-abcdefghijklmnopqrstuvwxyz")
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in redact("key=sk-abcdefghijklmnopqrstuvwxyz")


def test_github_tokens():
    text = (
        "ghp_abcdefghijklmnopqrstuvwxyzABCD "
        "gho_abcdefghijklmnopqrstuvwxyzABCD "
        "ghu_abcdefghijklmnopqrstuvwxyzABCD "
        "ghs_abcdefghijklmnopqrstuvwxyzABCD "
        "github_pat_abcdefghijklmnopqrstuvwxyzABCD"
    )
    out = redact(text)
    assert "ghp_" not in out and "gho_" not in out
    assert "ghu_" not in out and "ghs_" not in out
    assert "github_pat_" not in out
    assert out.count(REDACTED) >= 5


def test_aws_access_key():
    assert "AKIAIOSFODNN7EXAMPLE" not in redact("id=AKIAIOSFODNN7EXAMPLE")


def test_jwt_and_bearer():
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaSJ9."
        "signaturepartlongenough"
    )
    bearer = redact(f"Authorization: Bearer {jwt}")
    raw = redact(f"token dump {jwt}")
    assert jwt not in bearer and jwt not in raw
    assert "Bearer" in bearer and REDACTED in bearer and REDACTED in raw


def test_private_key_block():
    block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAK\n-----END RSA PRIVATE KEY-----"
    assert "MIIEowIBAAK" not in redact(block)


def test_email():
    out = redact("Contact owner@deflake.local please")
    assert "owner@deflake.local" not in out
    assert REDACTED_EMAIL in out


def test_home_paths():
    unix = redact("traceback in /home/meera/proj/shop/pricing.py line 4")
    win = redact(r"File C:\Users\meera\proj\shop\pricing.py")
    assert "/home/meera" not in unix and REDACTED_PATH in unix
    assert r"C:\Users\meera" not in win and REDACTED_PATH in win


def test_key_assignment():
    out = redact("API_KEY=supersecrettokenvalue123")
    assert "supersecrettokenvalue123" not in out
    assert REDACTED in out


def test_nested_structures():
    data = redact_obj({"log": "user judge@deflake.local used sk-abcdefghijklmnopqrstuvwxyz"})
    assert "judge@" not in data["log"]
    assert "sk-" not in data["log"]
