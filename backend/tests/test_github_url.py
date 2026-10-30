import pytest

from app.integrations.github.url import GitHubUrlError, parse_github_repo_url


@pytest.mark.parametrize(
    "raw",
    [
        "https://github.com/acme/shop",
        "https://github.com/acme/shop/",
        "https://github.com/acme/shop.git",
        "https://github.com/acme/shop.git/",
        "https://github.com/Acme-Org/my_shop.v2",
    ],
)
def test_valid_github_urls(raw):
    parsed = parse_github_repo_url(raw)
    assert parsed.clone_url == f"https://github.com/{parsed.owner}/{parsed.name}.git"
    assert parsed.html_url.startswith("https://github.com/")
    assert " " not in parsed.html_url


def test_rebuilds_url_and_ignores_caller_string_casing_path():
    parsed = parse_github_repo_url("https://github.com/hukkin/tomli/")
    assert parsed.owner == "hukkin"
    assert parsed.name == "tomli"
    assert parsed.html_url == "https://github.com/hukkin/tomli"


@pytest.mark.parametrize(
    "raw",
    [
        "http://github.com/acme/shop",
        "https://gitlab.com/acme/shop",
        "https://www.github.com/acme/shop",
        "https://github.example.com/acme/shop",
        "https://evil.com/acme/shop",
    ],
)
def test_rejects_other_hosts_and_schemes(raw):
    with pytest.raises(GitHubUrlError):
        parse_github_repo_url(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "https://github.com/acme/shop?foo=1",
        "https://github.com/acme/shop#readme",
        "https://github.com/acme/shop?x=1#y",
    ],
)
def test_rejects_query_and_fragment(raw):
    with pytest.raises(GitHubUrlError):
        parse_github_repo_url(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "https://github.com:443/acme/shop",
        "https://github.com:8080/acme/shop",
    ],
)
def test_rejects_port(raw):
    with pytest.raises(GitHubUrlError):
        parse_github_repo_url(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "https://user@github.com/acme/shop",
        "https://user:pass@github.com/acme/shop",
    ],
)
def test_rejects_userinfo(raw):
    with pytest.raises(GitHubUrlError):
        parse_github_repo_url(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "https://github.com/acme/..",
        "https://github.com/acme/.",
        "https://github.com/acme/../shop",
        "https://github.com/acme/shop/extra",
        "https://github.com/acme",
        "https://github.com/",
        "not-a-url",
        "",
    ],
)
def test_rejects_dot_dot_and_malformed_paths(raw):
    with pytest.raises(GitHubUrlError):
        parse_github_repo_url(raw)


def test_rejects_owner_with_leading_or_trailing_hyphen():
    with pytest.raises(GitHubUrlError):
        parse_github_repo_url("https://github.com/-acme/shop")
    with pytest.raises(GitHubUrlError):
        parse_github_repo_url("https://github.com/acme-/shop")
