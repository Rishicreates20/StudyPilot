"""Structural rules from CLAUDE.md that are cheap to check mechanically and costly to break."""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

# Code that serves web requests. It must only ever see the caller's own rows.
REQUEST_PACKAGES = ("api", "services", "repositories", "schemas")
PRIVILEGED_NAMES = {"system_session", "SystemConnection"}


def python_files(*packages: str) -> list[Path]:
    return sorted(path for package in packages for path in (APP / package).rglob("*.py"))


def names_used(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.name.split(".")[-1])
    return names


def test_there_is_request_code_to_check() -> None:
    assert len(python_files(*REQUEST_PACKAGES)) >= 10


@pytest.mark.parametrize(
    "path", python_files(*REQUEST_PACKAGES), ids=lambda p: str(p.relative_to(APP))
)
def test_web_request_code_never_uses_the_privileged_database_session(path: Path) -> None:
    assert names_used(path) & PRIVILEGED_NAMES == set()


def test_only_the_worker_packages_use_the_privileged_session() -> None:
    users = {
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if names_used(path) & PRIVILEGED_NAMES
    }

    allowed_prefixes = ("jobs", "worker.py", "core")
    assert users, "the worker should use it somewhere"
    assert all(user.startswith(allowed_prefixes) for user in users), users


@pytest.mark.parametrize(
    "path", python_files(*REQUEST_PACKAGES, "ai"), ids=lambda p: str(p.relative_to(APP))
)
def test_nothing_reads_a_service_role_or_secret_key(path: Path) -> None:
    text = path.read_text(encoding="utf-8").lower()

    assert "service_role" not in text
    assert "supabase_secret" not in text
