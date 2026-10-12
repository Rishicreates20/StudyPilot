"""The API against a genuine Supabase stack (GoTrue, its real roles, schema and signing keys).

Everything else in the suite runs against a stand-in for Supabase's roles and ``auth`` schema and
against tokens we sign ourselves. These tests close that gap: accounts are created through
Supabase Auth's own HTTP API, the access tokens it issues are verified by our verifier, and Row
Level Security is exercised with Supabase's real ``anon``/``authenticated`` roles and the real
``auth.users`` table.

They need a running stack (``npx supabase start``) and are skipped otherwise. CI runs them in the
``supabase-stack`` job, which exports the variables below with
``.github/scripts/supabase_stack_env.py``.

    SUPABASE_STACK_URL              http://127.0.0.1:54321
    SUPABASE_STACK_PUBLISHABLE_KEY  the stack's publishable (or legacy anon) key
    SUPABASE_STACK_DB_URL           postgresql://postgres:...@127.0.0.1:54322/postgres
    SUPABASE_STACK_JWT_SECRET       only needed when the stack signs tokens with HS256

Supabase Auth rate-limits sign-ups and sign-ins per IP; supabase/config.toml raises the limit for
the local stack, and each test still creates only the accounts it needs.
"""

import base64
import json
import os
import secrets
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx2
import jwt
import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.rows import DictRow, dict_row
from pydantic import SecretStr

from app.core.config import AppEnv, JwtMode, LlmProviderName, Settings
from app.main import create_app
from conftest import new_client
from support.api_helpers import topic_ids
from support.settings import IsolatedSettings
from support.worker import clear_queue, run_worker_once

STACK_URL = os.environ.get("SUPABASE_STACK_URL", "").rstrip("/")
PUBLISHABLE_KEY = os.environ.get("SUPABASE_STACK_PUBLISHABLE_KEY", "")
DB_URL = os.environ.get("SUPABASE_STACK_DB_URL", "")
JWT_SECRET = os.environ.get("SUPABASE_STACK_JWT_SECRET", "")

if not (STACK_URL and PUBLISHABLE_KEY and DB_URL):
    _MISSING = (
        "No Supabase stack configured (set SUPABASE_STACK_URL, SUPABASE_STACK_PUBLISHABLE_KEY and "
        "SUPABASE_STACK_DB_URL; see the module docstring)."
    )
    if os.environ.get("REQUIRE_SUPABASE_STACK") == "1":
        # CI sets this: a stack job whose tests were silently skipped would prove nothing.
        raise RuntimeError(_MISSING)
    pytest.skip(_MISSING, allow_module_level=True)

AUTH_URL = f"{STACK_URL}/auth/v1"


@dataclass(frozen=True)
class Account:
    """A user created through Supabase Auth, with the session it returned."""

    id: uuid.UUID
    email: str
    password: str
    access_token: str
    refresh_token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


def _auth_error(response: httpx2.Response) -> str:
    return f"Supabase Auth answered {response.status_code}: {response.text[:300]}"


@pytest.fixture(scope="module")
def auth() -> Iterator[httpx2.Client]:
    with httpx2.Client(
        base_url=AUTH_URL, headers={"apikey": PUBLISHABLE_KEY}, timeout=30.0
    ) as client:
        yield client


@pytest.fixture(scope="module")
def sign_up(auth: httpx2.Client) -> Callable[..., Account]:
    def create(*, display_name: str | None = None) -> Account:
        email = f"learner-{uuid.uuid4().hex[:12]}@example.test"
        password = secrets.token_urlsafe(18)
        body: dict[str, Any] = {"email": email, "password": password}
        if display_name is not None:
            body["data"] = {"display_name": display_name}
        response = auth.post("/signup", json=body)
        assert response.status_code == 200, _auth_error(response)
        payload = response.json()
        assert payload.get("access_token"), (
            "Sign-up returned no session: email confirmation must be off for the local stack "
            "(supabase/config.toml: [auth.email] enable_confirmations = false)"
        )
        return Account(
            id=uuid.UUID(payload["user"]["id"]),
            email=email,
            password=password,
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
        )

    return create


@pytest.fixture(scope="module")
def signing_algorithm(sign_up: Callable[..., Account]) -> str:
    """The algorithm this stack signs access tokens with (decides how the API verifies them)."""
    return str(jwt.get_unverified_header(sign_up().access_token)["alg"])


@pytest.fixture(scope="module")
def settings(signing_algorithm: str) -> Settings:
    if signing_algorithm == "HS256":
        assert JWT_SECRET, "The stack signs with HS256: set SUPABASE_STACK_JWT_SECRET"
        return IsolatedSettings(
            app_env=AppEnv.TEST,
            database_url=SecretStr(DB_URL),
            supabase_url=STACK_URL,
            supabase_jwt_mode=JwtMode.HS256,
            supabase_jwt_secret=SecretStr(JWT_SECRET),
            db_pool_max_size=4,
            llm_provider=LlmProviderName.FAKE,
        )
    return IsolatedSettings(
        app_env=AppEnv.TEST,
        database_url=SecretStr(DB_URL),
        supabase_url=STACK_URL,
        supabase_jwt_mode=JwtMode.JWKS,
        db_pool_max_size=4,
        llm_provider=LlmProviderName.FAKE,
    )


@pytest.fixture(scope="module")
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture(scope="module")
def api(app: FastAPI) -> Iterator[TestClient]:
    with new_client(app) as client:
        assert client.get("/readyz").status_code == 200, "the API cannot reach the stack database"
        yield client


@pytest.fixture(scope="module")
def database() -> Iterator[psycopg.Connection[DictRow]]:
    """A superuser connection to the stack's database, for assertions the API cannot make."""
    with psycopg.Connection[DictRow].connect(
        DB_URL, autocommit=True, row_factory=dict_row
    ) as connection:
        yield connection


def create_goal(api: TestClient, account: Account, title: str) -> dict[str, Any]:
    response = api.post("/v1/goals", headers=account.headers, json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


# --- Account lifecycle against real Supabase Auth -----------------------------------------------


def test_a_new_account_is_recognised_by_the_api_and_has_a_profile(
    api: TestClient, sign_up: Callable[..., Account]
) -> None:
    account = sign_up(display_name="Ada Lovelace")

    response = api.get("/v1/me", headers=account.headers)

    assert response.status_code == 200, response.text
    me = response.json()
    assert me["id"] == str(account.id)
    assert me["email"] == account.email
    assert me["display_name"] == "Ada Lovelace"  # copied by the on_auth_user_created trigger


def test_signing_in_again_issues_a_working_session(
    api: TestClient, auth: httpx2.Client, sign_up: Callable[..., Account]
) -> None:
    account = sign_up()

    response = auth.post(
        "/token",
        params={"grant_type": "password"},
        json={"email": account.email, "password": account.password},
    )

    assert response.status_code == 200, _auth_error(response)
    token = response.json()["access_token"]
    assert api.get("/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_supabase_rejects_a_wrong_password(
    auth: httpx2.Client, sign_up: Callable[..., Account]
) -> None:
    account = sign_up()

    response = auth.post(
        "/token",
        params={"grant_type": "password"},
        json={"email": account.email, "password": "not-the-password-1234"},
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_credentials"


def test_a_session_can_be_renewed_and_the_new_token_works(
    api: TestClient, auth: httpx2.Client, sign_up: Callable[..., Account]
) -> None:
    account = sign_up()

    response = auth.post(
        "/token",
        params={"grant_type": "refresh_token"},
        json={"refresh_token": account.refresh_token},
    )

    assert response.status_code == 200, _auth_error(response)
    renewed = response.json()
    assert renewed["refresh_token"] != account.refresh_token  # rotated
    me = api.get("/v1/me", headers={"Authorization": f"Bearer {renewed['access_token']}"})
    assert me.status_code == 200
    assert me.json()["id"] == str(account.id)


def test_signing_out_ends_the_session_so_it_cannot_be_renewed(
    auth: httpx2.Client, sign_up: Callable[..., Account]
) -> None:
    account = sign_up()

    logout = auth.post("/logout", params={"scope": "local"}, headers=account.headers)
    renewal = auth.post(
        "/token",
        params={"grant_type": "refresh_token"},
        json={"refresh_token": account.refresh_token},
    )

    assert logout.status_code == 204, _auth_error(logout)
    assert renewal.status_code in {400, 401}, _auth_error(renewal)


# --- Ownership across users ---------------------------------------------------------------------


def test_one_learner_cannot_see_or_open_anothers_goals(
    api: TestClient, sign_up: Callable[..., Account]
) -> None:
    ada, grace = sign_up(), sign_up()
    adas_goal = create_goal(api, ada, "Ada's private goal")
    create_goal(api, grace, "Grace's goal")

    graces_list = api.get("/v1/goals", headers=grace.headers).json()["items"]
    adas_list = api.get("/v1/goals", headers=ada.headers).json()["items"]
    opened_by_grace = api.get(f"/v1/goals/{adas_goal['id']}", headers=grace.headers)

    assert [goal["title"] for goal in graces_list] == ["Grace's goal"]
    assert [goal["title"] for goal in adas_list] == ["Ada's private goal"]
    assert opened_by_grace.status_code == 404  # not 403: existence is not revealed
    assert "Ada's private goal" not in opened_by_grace.text


def test_a_body_naming_another_owner_is_refused(
    api: TestClient, sign_up: Callable[..., Account]
) -> None:
    ada, grace = sign_up(), sign_up()

    response = api.post(
        "/v1/goals", headers=ada.headers, json={"title": "Sneaky", "user_id": str(grace.id)}
    )

    assert response.status_code == 422
    assert api.get("/v1/goals", headers=grace.headers).json()["items"] == []


# --- Token verification against genuine Supabase tokens -----------------------------------------


def _b64(data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_requests_without_a_token_are_refused(api: TestClient) -> None:
    for path in ("/v1/me", "/v1/goals"):
        response = api.get(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


def test_a_real_token_with_its_subject_swapped_is_refused(
    api: TestClient, sign_up: Callable[..., Account]
) -> None:
    ada, grace = sign_up(), sign_up()
    header, payload, signature = ada.access_token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["sub"] = str(grace.id)  # claim to be Grace, keep Ada's signature

    forged = f"{header}.{_b64(claims)}.{signature}"

    response = api.get("/v1/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_an_unsigned_token_naming_a_real_user_is_refused(
    api: TestClient, sign_up: Callable[..., Account]
) -> None:
    account = sign_up()
    now = int(time.time())
    claims = {
        "sub": str(account.id),
        "role": "authenticated",
        "aud": "authenticated",
        "iss": AUTH_URL,
        "iat": now,
        "exp": now + 3600,
    }

    unsigned = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(claims)}."

    response = api.get("/v1/me", headers={"Authorization": f"Bearer {unsigned}"})
    assert response.status_code == 401


def test_a_token_signed_with_some_other_secret_is_refused(
    api: TestClient, sign_up: Callable[..., Account]
) -> None:
    account = sign_up()
    now = int(time.time())
    forged = jwt.encode(
        {
            "sub": str(account.id),
            "role": "authenticated",
            "aud": "authenticated",
            "iss": AUTH_URL,
            "iat": now,
            "exp": now + 3600,
        },
        secrets.token_urlsafe(48),
        algorithm="HS256",
    )

    response = api.get("/v1/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_an_expired_token_is_reported_as_expired(
    api: TestClient, signing_algorithm: str, sign_up: Callable[..., Account]
) -> None:
    if signing_algorithm != "HS256":
        pytest.skip("Only a stack that signs with the shared secret lets a test mint a token.")
    account = sign_up()
    now = int(time.time())
    expired = jwt.encode(
        {
            "sub": str(account.id),
            "role": "authenticated",
            "aud": "authenticated",
            "iss": AUTH_URL,
            "iat": now - 7200,
            "exp": now - 3600,
        },
        JWT_SECRET,
        algorithm="HS256",
    )

    response = api.get("/v1/me", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_EXPIRED"


# --- Database rules against Supabase's real roles ------------------------------------------------


def _act_as(database: psycopg.Connection[DictRow], role: str, user_id: uuid.UUID | None) -> None:
    claims = {"role": role, **({"sub": str(user_id)} if user_id else {})}
    database.execute(
        "select set_config('role', %s, true), set_config('request.jwt.claims', %s, true)",
        (role, json.dumps(claims)),
    )


def test_row_level_security_isolates_users_under_the_real_roles(
    api: TestClient,
    database: psycopg.Connection[DictRow],
    sign_up: Callable[..., Account],
) -> None:
    ada, grace = sign_up(), sign_up()
    create_goal(api, ada, "Ada's goal")
    create_goal(api, grace, "Grace's goal")

    with database.transaction(force_rollback=True):
        _act_as(database, "authenticated", ada.id)
        seen = [row["title"] for row in database.execute("select title from public.learning_goals")]
        assert seen == ["Ada's goal"]

    with database.transaction(force_rollback=True):
        _act_as(database, "authenticated", ada.id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            database.execute(
                "insert into public.learning_goals (user_id, title) values (%s, 'Forged')",
                (grace.id,),
            )

    with database.transaction(force_rollback=True):
        _act_as(database, "authenticated", ada.id)
        updated = database.execute(
            "update public.profiles set display_name = 'Hijacked' where id = %s", (grace.id,)
        )
        assert updated.rowcount == 0  # RLS hides Grace's profile from Ada


def test_the_anonymous_role_has_no_table_access(
    database: psycopg.Connection[DictRow],
) -> None:
    for table in ("public.profiles", "public.learning_goals"):
        for privilege in ("select", "insert", "update", "delete"):
            allowed = database.execute(
                "select has_table_privilege('anon', %s, %s) as ok", (table, privilege)
            ).fetchone()
            assert allowed is not None and allowed["ok"] is False, f"anon can {privilege} {table}"


def test_the_data_api_does_not_expose_application_tables(
    api: TestClient, sign_up: Callable[..., Account]
) -> None:
    account = sign_up()
    create_goal(api, account, "Not reachable through PostgREST")

    response = httpx2.get(
        f"{STACK_URL}/rest/v1/learning_goals",
        headers={"apikey": PUBLISHABLE_KEY, **account.headers},
        timeout=30.0,
    )

    assert "Not reachable through PostgREST" not in response.text
    assert response.status_code != 200 or response.json() == []


def test_deleting_an_account_removes_its_data_and_locks_out_its_token(
    api: TestClient,
    database: psycopg.Connection[DictRow],
    sign_up: Callable[..., Account],
) -> None:
    account = sign_up()
    create_goal(api, account, "Goes away with the account")
    assert api.get("/v1/me", headers=account.headers).status_code == 200

    database.execute("delete from auth.users where id = %s", (account.id,))

    remaining = database.execute(
        "select (select count(*) from public.profiles where id = %(id)s) as profiles,"
        " (select count(*) from public.learning_goals where user_id = %(id)s) as goals",
        {"id": account.id},
    ).fetchone()
    assert remaining == {"profiles": 0, "goals": 0}
    # The access token is still cryptographically valid, but the account is gone.
    response = api.get("/v1/me", headers=account.headers)
    assert response.status_code == 401
    assert response.json()["code"] == "ACCOUNT_NOT_FOUND"


# --- Managing goals, under genuine Supabase tokens, roles and grants ---------------------------


def move(api: TestClient, account: Account, goal_id: str, status: str) -> Any:
    return api.put(f"/v1/goals/{goal_id}/status", headers=account.headers, json={"status": status})


def test_a_goal_can_be_edited_and_moved_through_its_lifecycle(
    api: TestClient, sign_up: Callable[..., Account]
) -> None:
    account = sign_up()
    goal = create_goal(api, account, "Learn Rust")

    edited = api.patch(
        f"/v1/goals/{goal['id']}",
        headers=account.headers,
        json={"title": "Learn Rust ownership", "daily_minutes": 45, "description": "Chapter 4"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["title"] == "Learn Rust ownership"

    for status in ("paused", "active", "completed", "active", "archived"):
        response = move(api, account, goal["id"], status)
        assert response.status_code == 200, f"{status}: {response.text}"
        assert response.json()["status"] == status

    archived = api.get(f"/v1/goals/{goal['id']}", headers=account.headers).json()
    assert archived["archived_at"] is not None and archived["completed_at"] is None
    refused = api.patch(f"/v1/goals/{goal['id']}", headers=account.headers, json={"title": "No"})
    assert refused.status_code == 409 and refused.json()["code"] == "GOAL_ARCHIVED"


def test_only_an_archived_goal_can_be_deleted(
    api: TestClient, sign_up: Callable[..., Account]
) -> None:
    account = sign_up()
    goal = create_goal(api, account, "Delete me twice")

    early = api.delete(f"/v1/goals/{goal['id']}", headers=account.headers)
    assert move(api, account, goal["id"], "archived").status_code == 200
    deleted = api.delete(f"/v1/goals/{goal['id']}", headers=account.headers)
    again = api.delete(f"/v1/goals/{goal['id']}", headers=account.headers)

    assert (early.status_code, deleted.status_code, again.status_code) == (409, 204, 404)


def test_another_learner_cannot_edit_move_or_delete_a_goal(
    api: TestClient, sign_up: Callable[..., Account]
) -> None:
    ada, mallory = sign_up(), sign_up()
    goal = create_goal(api, ada, "Ada's goal")
    move(api, ada, goal["id"], "archived")  # archived, so a delete would be legal for Ada

    edit = api.patch(f"/v1/goals/{goal['id']}", headers=mallory.headers, json={"title": "Mine"})
    status = move(api, mallory, goal["id"], "active")
    delete = api.delete(f"/v1/goals/{goal['id']}", headers=mallory.headers)

    assert [edit.status_code, status.status_code, delete.status_code] == [404, 404, 404]
    assert api.get(f"/v1/goals/{goal['id']}", headers=ada.headers).json()["status"] == "archived"


def test_the_database_itself_refuses_illegal_goal_changes_under_the_real_roles(
    api: TestClient,
    database: psycopg.Connection[DictRow],
    sign_up: Callable[..., Account],
) -> None:
    account = sign_up()
    goal = create_goal(api, account, "Guarded")

    # Columns the system owns are not writable by the authenticated role.
    with database.transaction(force_rollback=True):
        _act_as(database, "authenticated", account.id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            database.execute(
                "update public.learning_goals set completed_at = now() where id = %s", (goal["id"],)
            )
    # An illegal status jump, and a delete of a goal that is not archived, are refused too.
    with database.transaction(force_rollback=True):
        _act_as(database, "authenticated", account.id)
        database.execute(
            "update public.learning_goals set status = 'completed' where id = %s", (goal["id"],)
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            database.execute(
                "update public.learning_goals set status = 'paused' where id = %s", (goal["id"],)
            )
    with database.transaction(force_rollback=True):
        _act_as(database, "authenticated", account.id)
        deleted = database.execute("delete from public.learning_goals where id = %s", (goal["id"],))
        assert deleted.rowcount == 0


def test_preferences_and_onboarding_persist_and_shape_new_goals(
    api: TestClient, sign_up: Callable[..., Account]
) -> None:
    account = sign_up()
    assert api.get("/v1/me", headers=account.headers).json()["onboarding_completed"] is False

    saved = api.patch(
        "/v1/me",
        headers=account.headers,
        json={
            "default_daily_minutes": 90,
            "preferred_languages": ["hi"],
            "learning_preferences": ["quizzes"],
            "timezone": "Europe/London",
        },
    )
    done = api.post("/v1/me/onboarding/complete", headers=account.headers)
    goal = create_goal(api, account, "Starts from my preferences")

    assert saved.status_code == 200, saved.text
    assert done.json()["onboarding_completed"] is True
    me = api.get("/v1/me", headers=account.headers).json()
    assert me["timezone"] == "Europe/London"
    assert me["preferences"]["default_daily_minutes"] == 90
    assert (goal["daily_minutes"], goal["preferred_languages"], goal["learning_preferences"]) == (
        90,
        ["hi"],
        ["quizzes"],
    )


def test_one_learners_preferences_never_reach_another(
    api: TestClient, sign_up: Callable[..., Account]
) -> None:
    ada, grace = sign_up(), sign_up()

    api.patch("/v1/me", headers=ada.headers, json={"default_daily_minutes": 300})

    assert (
        api.get("/v1/me", headers=grace.headers).json()["preferences"]["default_daily_minutes"]
        == 60
    )


# --- Jobs and roadmaps under Supabase's real roles ------------------------------------------------


def generate_roadmap(api: TestClient, account: Account, goal_id: str) -> dict[str, Any]:
    """Queue a generation through the API and see it through (built-in provider).

    The real worker runs it here; if another worker happens to be running too and gets there
    first, the job still completes, so the test waits for the outcome rather than for its own run.
    """
    clear_queue(DB_URL)
    started = api.post(f"/v1/goals/{goal_id}/roadmaps", headers=account.headers, json={})
    assert started.status_code == 202, started.text
    run_worker_once(DB_URL)
    job: dict[str, Any] = {}
    for _ in range(40):
        job = api.get(f"/v1/jobs/{started.json()['id']}", headers=account.headers).json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.5)
    assert job["status"] == "completed", job
    return job


def test_a_roadmap_is_generated_stored_and_private_to_its_owner(
    api: TestClient, sign_up: Callable[..., Account]
) -> None:
    ada, grace = sign_up(), sign_up()
    goal = create_goal(api, ada, "Learn graph algorithms")

    job = generate_roadmap(api, ada, goal["id"])

    roadmap = api.get(f"/v1/roadmaps/{job['roadmap_id']}", headers=ada.headers)
    assert roadmap.status_code == 200, roadmap.text
    assert roadmap.json()["version"] == 1 and roadmap.json()["status"] == "current"
    assert roadmap.json()["modules"] and roadmap.json()["is_synthetic"] is True
    for path in (
        f"/v1/roadmaps/{job['roadmap_id']}",
        f"/v1/jobs/{job['id']}",
        f"/v1/goals/{goal['id']}/roadmaps",
    ):
        assert api.get(path, headers=grace.headers).status_code == 404, path
    assert (
        api.post(f"/v1/goals/{goal['id']}/roadmaps", headers=grace.headers, json={}).status_code
        == 404
    )


def test_versions_are_kept_and_switchable_under_the_real_roles(
    api: TestClient, sign_up: Callable[..., Account]
) -> None:
    ada = sign_up()
    goal = create_goal(api, ada, "Learn compilers")
    first = generate_roadmap(api, ada, goal["id"])
    second = generate_roadmap(api, ada, goal["id"])

    switched = api.post(f"/v1/roadmaps/{first['roadmap_id']}/make-current", headers=ada.headers)

    assert switched.status_code == 200, switched.text
    listing = api.get(f"/v1/goals/{goal['id']}/roadmaps", headers=ada.headers).json()
    assert listing["current_id"] == first["roadmap_id"]
    assert {v["id"]: v["status"] for v in listing["items"]} == {
        first["roadmap_id"]: "current",
        second["roadmap_id"]: "superseded",
    }


def test_the_real_roles_cannot_write_plans_or_job_state_directly(
    api: TestClient,
    database: psycopg.Connection[DictRow],
    sign_up: Callable[..., Account],
) -> None:
    ada, grace = sign_up(), sign_up()
    goal = create_goal(api, ada, "Learn operating systems")
    job = generate_roadmap(api, ada, goal["id"])

    for statement in (
        "update public.roadmaps set title = 'Rewritten'",
        "delete from public.roadmaps",
        "update public.roadmap_items set title = 'Rewritten'",
        "update public.generation_jobs set status = 'completed'",
        "delete from public.generation_jobs",
        "insert into public.ai_usage_events (user_id, job_id, purpose, provider, prompt_version)"
        " select user_id, id, 'x', 'fake', 'v' from public.generation_jobs",
    ):
        with database.transaction(force_rollback=True):
            _act_as(database, "authenticated", ada.id)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                database.execute(statement)  # type: ignore[arg-type]

    with database.transaction(force_rollback=True):
        _act_as(database, "authenticated", grace.id)
        for table in ("roadmaps", "roadmap_modules", "roadmap_items", "generation_jobs"):
            rows = database.execute(f"select 1 from public.{table}").fetchall()  # type: ignore[arg-type]  # noqa: S608
            assert rows == [], table
    for table in ("roadmaps", "roadmap_modules", "roadmap_items", "generation_jobs"):
        allowed = database.execute(
            "select has_table_privilege('anon', %s, 'select') as ok", (f"public.{table}",)
        ).fetchone()
        assert allowed is not None and allowed["ok"] is False, f"anon can read {table}"
    assert job["roadmap_id"]


def test_a_queued_job_can_be_cancelled_under_the_real_roles(
    api: TestClient, sign_up: Callable[..., Account]
) -> None:
    ada = sign_up()
    goal = create_goal(api, ada, "Learn databases")
    clear_queue(DB_URL)
    job = api.post(f"/v1/goals/{goal['id']}/roadmaps", headers=ada.headers, json={}).json()

    cancelled = api.post(f"/v1/jobs/{job['id']}/cancel", headers=ada.headers)

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert (
        api.post(f"/v1/goals/{goal['id']}/roadmaps", headers=ada.headers, json={}).status_code
        == 202
    )


def test_no_security_definer_function_in_public_is_callable_by_clients_on_real_supabase(
    database: psycopg.Connection[DictRow],
) -> None:
    """Supabase's default privileges grant execute on new `public` functions to the browser-facing
    roles. A SECURITY DEFINER function that keeps that grant is a door around row security (the
    platform's own `rls_auto_enable()` was one on hosted projects until a migration revoked it)."""
    leaks = database.execute(
        "select p.oid::regprocedure::text as function_name"
        " from pg_proc p join pg_namespace n on n.oid = p.pronamespace"
        " where n.nspname = 'public' and p.prosecdef"
        " and (has_function_privilege('anon', p.oid, 'execute')"
        " or has_function_privilege('authenticated', p.oid, 'execute'))"
    ).fetchall()

    assert leaks == [], f"callable by anon/authenticated: {[row['function_name'] for row in leaks]}"


# --- Lessons and quizzes under Supabase's real roles ---------------------------------------------


def finish_job(api: TestClient, account: Account, started: Any) -> dict[str, Any]:
    """Run the queued job with the real worker (or wait for another one that got there first)."""
    assert started.status_code == 202, started.text
    run_worker_once(DB_URL)
    job: dict[str, Any] = {}
    for _ in range(40):
        job = api.get(f"/v1/jobs/{started.json()['id']}", headers=account.headers).json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.5)
    assert job["status"] == "completed", job
    return job


def quiz_for_a_new_topic(api: TestClient, account: Account) -> tuple[str, str, str]:
    """A goal with a roadmap, a lesson and a written quiz: (goal id, topic id, quiz id)."""
    goal = create_goal(api, account, "Learn type theory")
    roadmap = api.get(
        f"/v1/roadmaps/{generate_roadmap(api, account, goal['id'])['roadmap_id']}",
        headers=account.headers,
    ).json()
    topic = topic_ids(roadmap)[0]
    clear_queue(DB_URL)
    finish_job(
        api,
        account,
        api.post(f"/v1/roadmap-items/{topic}/lessons", headers=account.headers, json={}),
    )
    clear_queue(DB_URL)
    quiz_job = finish_job(
        api,
        account,
        api.post(f"/v1/roadmap-items/{topic}/quizzes", headers=account.headers, json={}),
    )
    return goal["id"], topic, quiz_job["quiz_id"]


def test_a_quiz_is_written_taken_graded_and_private_to_its_owner(
    api: TestClient, sign_up: Callable[..., Account]
) -> None:
    ada, grace = sign_up(), sign_up()
    goal, topic, quiz_id = quiz_for_a_new_topic(api, ada)

    quiz = api.get(f"/v1/quizzes/{quiz_id}", headers=ada.headers)
    assert quiz.status_code == 200, quiz.text
    for secret in ("correct_option", "explanation", "rubric", "model_answer", "option_notes"):
        assert secret not in quiz.text, secret

    submitted = api.post(
        f"/v1/quizzes/{quiz_id}/attempts", headers=ada.headers, json={"answers": []}
    )
    assert submitted.status_code == 201, submitted.text
    result = submitted.json()
    assert result["status"] == "graded" and result["percent"] == 0
    assert all(answer["feedback"]["explanation"] for answer in result["answers"])
    assert (
        api.post(
            f"/v1/quizzes/{quiz_id}/attempts", headers=ada.headers, json={"answers": []}
        ).status_code
        == 409
    )
    progress = api.get(f"/v1/goals/{goal}/progress", headers=ada.headers).json()
    assert progress["counts"]["needs_practice"] == 1

    attempts: list[tuple[str, str, dict[str, Any] | None]] = [
        ("get", f"/v1/quizzes/{quiz_id}", None),
        ("post", f"/v1/quizzes/{quiz_id}/attempts", {"answers": []}),
        ("get", f"/v1/quiz-attempts/{result['id']}", None),
        ("get", f"/v1/roadmap-items/{topic}/assessment", None),
        ("post", f"/v1/roadmap-items/{topic}/quizzes", {}),
        ("get", f"/v1/goals/{goal}/progress", None),
    ]
    for method, path, body in attempts:
        response = api.request(method, path, headers=grace.headers, json=body)
        assert response.status_code == 404, (path, response.status_code)


def test_the_real_roles_cannot_read_answer_keys_or_write_assessment_tables(
    api: TestClient,
    database: psycopg.Connection[DictRow],
    sign_up: Callable[..., Account],
) -> None:
    ada, grace = sign_up(), sign_up()
    _, _, quiz_id = quiz_for_a_new_topic(api, ada)
    api.post(f"/v1/quizzes/{quiz_id}/attempts", headers=ada.headers, json={"answers": []})

    for role, user in (("authenticated", ada.id), ("anon", None)):
        with database.transaction(force_rollback=True):
            _act_as(database, role, user)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                database.execute("select * from public.question_answer_keys")

    for statement in (
        "update public.quizzes set title = 'Rewritten'",
        "update public.questions set prompt = 'Rewritten'",
        "update public.quiz_attempts set percent = 100",
        "update public.quiz_answers set points_awarded = max_points",
        "update public.topic_mastery set score = 100",
        "delete from public.quiz_answers",
        "insert into public.generation_jobs (user_id, goal_id, job_type) select user_id, goal_id,"
        " 'grade' from public.generation_jobs limit 1",
    ):
        with database.transaction(force_rollback=True):
            _act_as(database, "authenticated", ada.id)
            with pytest.raises(
                (psycopg.errors.InsufficientPrivilege, psycopg.errors.CheckViolation)
            ):
                database.execute(statement)  # type: ignore[arg-type]

    with database.transaction(force_rollback=True):
        _act_as(database, "authenticated", grace.id)
        for table in ("quizzes", "questions", "quiz_attempts", "quiz_answers", "topic_mastery"):
            rows = database.execute(f"select 1 from public.{table}").fetchall()  # type: ignore[arg-type]  # noqa: S608
            assert rows == [], table
    for table in ("question_answer_keys", "quizzes", "quiz_attempts", "topic_mastery"):
        allowed = database.execute(
            "select has_table_privilege('anon', %s, 'select') as ok", (f"public.{table}",)
        ).fetchone()
        assert allowed is not None and allowed["ok"] is False, f"anon can read {table}"
    keys = database.execute(
        "select has_table_privilege('authenticated', 'public.question_answer_keys', 'select') as ok"
    ).fetchone()
    assert keys is not None and keys["ok"] is False


# --- Study documents: private files, pages, passages and vectors ----------------------------------

DOCUMENT_TEXT = (
    "Ownership is the rule that makes Rust memory safe. Each value has exactly one owner, and "
    "the value is dropped when its owner goes out of scope."
)


@pytest.fixture
def local_files(app: FastAPI, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Uploaded files go to a temporary folder: the stack under test is Auth and the database."""
    from app.documents.storage import LocalFiles

    files = LocalFiles(tmp_path / "files")
    monkeypatch.setattr(app.state, "files", files)
    return files


def add_document(
    api: TestClient, account: Account, goal_id: str, files: Any, text: str = DOCUMENT_TEXT
) -> dict[str, Any]:
    """Upload ``text`` and let the real worker read and index it. Returns the finished document."""
    clear_queue(DB_URL)
    response = api.post(
        f"/v1/goals/{goal_id}/documents",
        headers={**account.headers, "Content-Type": "application/octet-stream"},
        params={"name": "notes.txt", "title": "Rust notes"},
        content=text.encode(),
    )
    assert response.status_code == 202, response.text
    run_worker_once(DB_URL, files=files)
    document: dict[str, Any] = {}
    for _ in range(40):
        document = api.get(f"/v1/documents/{response.json()['id']}", headers=account.headers).json()
        if document["status"] in {"ready", "failed", "review"}:
            break
        time.sleep(0.5)
    assert document["status"] == "ready", document
    return document


def test_pgvector_is_installed_and_documents_are_indexed_and_found_under_the_real_roles(
    api: TestClient,
    database: psycopg.Connection[DictRow],
    sign_up: Callable[..., Account],
    local_files: Any,
) -> None:
    ada, grace = sign_up(), sign_up()
    goal = create_goal(api, ada, "Learn Rust")

    document = add_document(api, ada, goal["id"], local_files)

    extension = database.execute(
        "select e.extname, n.nspname from pg_extension e join pg_namespace n"
        " on n.oid = e.extnamespace where e.extname = 'vector'"
    ).fetchone()
    assert extension is not None and extension["nspname"] == "extensions"
    dims = database.execute(
        "select distinct extensions.vector_dims(embedding) as dims from public.document_chunks"
        " where document_id = %s",
        (document["id"],),
    ).fetchall()
    assert [row["dims"] for row in dims] == [1536]
    found = api.post(
        f"/v1/goals/{goal['id']}/documents/search",
        headers=ada.headers,
        json={"query": "what does ownership mean in Rust"},
    ).json()
    assert found["enough_evidence"] is True
    assert found["items"][0]["document_id"] == document["id"]

    # Another learner can neither search Ada's goal nor see her documents.
    searched = api.post(
        f"/v1/goals/{goal['id']}/documents/search",
        headers=grace.headers,
        json={"query": "ownership"},
    )
    assert searched.status_code == 404
    assert api.get(f"/v1/documents/{document['id']}", headers=grace.headers).status_code == 404
    pages = api.get(f"/v1/documents/{document['id']}/pages", headers=grace.headers)
    assert pages.status_code == 404


def test_the_real_roles_see_only_their_own_documents_and_cannot_write_the_worker_tables(
    api: TestClient,
    database: psycopg.Connection[DictRow],
    sign_up: Callable[..., Account],
    local_files: Any,
) -> None:
    ada, grace = sign_up(), sign_up()
    goal = create_goal(api, ada, "Learn Rust")
    document = add_document(api, ada, goal["id"], local_files)

    with database.transaction(force_rollback=True):
        _act_as(database, "authenticated", grace.id)
        for table in ("source_documents", "document_pages", "document_chunks"):
            rows = database.execute(f"select 1 from public.{table}").fetchall()  # type: ignore[arg-type]  # noqa: S608
            assert rows == [], table
    with database.transaction(force_rollback=True):
        _act_as(database, "authenticated", ada.id)
        seen = database.execute("select id from public.source_documents").fetchall()
        assert [str(row["id"]) for row in seen] == [document["id"]]

    for statement in (
        "update public.source_documents set status = 'ready'",
        "update public.source_documents set sha256 = repeat('0', 64)",
        "insert into public.document_pages (user_id, document_id, page_number, text, source)"
        " select user_id, id, 99, 'x', 'text' from public.source_documents",
        "update public.document_chunks set content = 'rewritten'",
        "delete from public.document_chunks",
        "insert into public.document_chunks (user_id, goal_id, document_id, chunk_index,"
        " page_start, page_end, content, embedding, embedding_model)"
        " select user_id, goal_id, id, 99, 1, 1, 'x',"
        " array_fill(0, array[1536])::extensions.vector, 'm' from public.source_documents",
    ):
        with database.transaction(force_rollback=True):
            _act_as(database, "authenticated", ada.id)
            with pytest.raises(
                (psycopg.errors.InsufficientPrivilege, psycopg.errors.CheckViolation)
            ):
                database.execute(statement)  # type: ignore[arg-type]

    for table in ("source_documents", "document_pages", "document_chunks"):
        for privilege in ("select", "insert", "update", "delete"):
            allowed = database.execute(
                "select has_table_privilege('anon', %s, %s) as ok", (f"public.{table}", privilege)
            ).fetchone()
            assert allowed is not None and allowed["ok"] is False, f"anon can {privilege} {table}"


def _storage_ready() -> bool:
    """Whether this stack runs Supabase Storage with the documents bucket (CI's does not)."""
    keys = {"apikey": PUBLISHABLE_KEY, "Authorization": f"Bearer {PUBLISHABLE_KEY}"}
    try:
        response = httpx2.get(f"{STACK_URL}/storage/v1/bucket/documents", headers=keys, timeout=5.0)
    except httpx2.HTTPError:
        return False
    return response.status_code in {200, 400, 401, 403}


@pytest.mark.skipif(
    not _storage_ready(),
    reason="This stack has no Supabase Storage (CI starts it without storage-api).",
)
def test_private_storage_lets_a_learner_reach_only_their_own_files(
    sign_up: Callable[..., Account],
) -> None:
    ada, grace = sign_up(), sign_up()
    path = f"{ada.id}/{uuid.uuid4()}/notes.txt"
    base = f"{STACK_URL}/storage/v1"

    def keys(who: Account) -> dict[str, str]:
        return {"apikey": PUBLISHABLE_KEY, **who.headers}

    stored = httpx2.post(
        f"{base}/object/documents/{path}",
        headers={**keys(ada), "Content-Type": "text/plain"},
        content=b"hello",
        timeout=30,
    )
    assert stored.status_code == 200, stored.text

    # The owner reads it; another learner and a signed-out visitor can neither read it nor write
    # under the owner's prefix.
    mine = httpx2.get(
        f"{base}/object/authenticated/documents/{path}", headers=keys(ada), timeout=30
    )
    assert mine.content == b"hello"
    forged = httpx2.post(
        f"{base}/object/documents/{ada.id}/{uuid.uuid4()}/planted.txt",
        headers={**keys(grace), "Content-Type": "text/plain"},
        content=b"x",
        timeout=30,
    )
    assert forged.status_code in {400, 401, 403, 404}
    theirs = httpx2.get(
        f"{base}/object/authenticated/documents/{path}", headers=keys(grace), timeout=30
    )
    assert theirs.status_code in {400, 401, 403, 404}
    public = httpx2.get(f"{base}/object/public/documents/{path}", timeout=30)
    assert public.status_code in {400, 401, 403, 404}

    # A signed link reads exactly that object and nothing else.
    signed = httpx2.post(
        f"{base}/object/sign/documents/{path}",
        headers=keys(ada),
        json={"expiresIn": 60},
        timeout=30,
    )
    assert signed.status_code == 200, signed.text
    assert httpx2.get(f"{base}{signed.json()['signedURL']}", timeout=30).content == b"hello"

    assert httpx2.delete(
        f"{base}/object/documents/{path}", headers=keys(ada), timeout=30
    ).is_success
