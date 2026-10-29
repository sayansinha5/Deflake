"""Selects an escalation provider from settings. A blank key falls through to local."""
from app.config import Settings
from app.integrations.escalation.github import GitHubIssueProvider
from app.integrations.escalation.local import LocalProvider
from app.integrations.escalation.tendem import TendemProvider


def build_provider(settings: Settings, name: str):
    if name == "tendem":
        return TendemProvider(settings)
    if name == "github_issue":
        return GitHubIssueProvider(settings)
    return LocalProvider()
