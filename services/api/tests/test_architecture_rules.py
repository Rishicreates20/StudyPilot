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

    allowed_prefixes = ("jobs", "worker.py", "core", "grading")
    assert users, "the worker should use it somewhere"
    assert all(user.startswith(allowed_prefixes) for user in users), users


@pytest.mark.parametrize(
    "path", python_files(*REQUEST_PACKAGES, "ai"), ids=lambda p: str(p.relative_to(APP))
)
def test_nothing_reads_a_service_role_or_secret_key(path: Path) -> None:
    text = path.read_text(encoding="utf-8").lower()

    assert "service_role" not in text
    assert "supabase_secret" not in text


# --- Assessment secrets (ADR-007, ADR-036) -----------------------------------------------------


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def test_only_the_quiz_service_may_call_the_grader() -> None:
    users = {
        path.relative_to(APP).as_posix()
        for path in python_files(*REQUEST_PACKAGES)
        if any(module.startswith("app.grading") for module in imported_modules(path))
    }

    assert users == {"services/quizzes.py"}, users


@pytest.mark.parametrize(
    "path", python_files(*REQUEST_PACKAGES), ids=lambda p: str(p.relative_to(APP))
)
def test_request_code_never_touches_the_answer_key_table(path: Path) -> None:
    assert "question_answer_keys" not in path.read_text(encoding="utf-8")


def test_the_answer_key_table_is_only_named_where_keys_are_written_or_graded() -> None:
    users = {
        path.relative_to(APP).as_posix()
        for path in python_files("jobs", "grading", "ai", "learning", "core")
        if "question_answer_keys" in path.read_text(encoding="utf-8")
    }

    # quiz_store writes the keys, attempts reads them at submission; the schema only documents them.
    assert users == {"jobs/quiz_store.py", "grading/attempts.py", "ai/quiz/schema.py"}, users


def test_the_grader_does_not_depend_on_the_web_layer() -> None:
    for path in python_files("grading", "learning"):
        modules = imported_modules(path)
        assert not any(
            module.startswith(("app.api", "app.services", "app.schemas", "app.repositories"))
            for module in modules
        ), path


def test_the_scoring_rules_are_pure() -> None:
    forbidden = ("psycopg", "app.core.db", "fastapi", "httpx", "app.ai.provider")
    for path in python_files("learning"):
        modules = imported_modules(path)
        assert not any(module.startswith(forbidden) for module in modules), path


def test_the_export_renderers_are_pure() -> None:
    """Rendering a PDF or a deck reads no database, storage or network: only the data it is given.
    ``app/exports/files.py`` is the one module there that talks to storage."""
    forbidden = ("psycopg", "app.core.db", "app.repositories", "app.jobs", "fastapi", "httpx")
    renderers = [path for path in python_files("exports") if path.name != "files.py"]
    assert renderers
    for path in renderers:
        modules = imported_modules(path)
        assert not any(module.startswith(forbidden) for module in modules), path
