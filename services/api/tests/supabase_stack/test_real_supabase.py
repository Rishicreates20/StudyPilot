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

from app.core.config import AppEnv, JwtMode, Settings
from app.main import create_app
from conftest import new_client
from support.settings import IsolatedSettings

STACK_URL = os.environ.get("SUPABASE_STACK_URL", "").rstrip("/")
PUBLISHABLE_KEY = os.environ.get("SUPABASE_STACK_PUBLISHABLE_KEY", "")
DB_URL = os.environ.get("SUPABASE_STACK_DB_URL", "")
JWT_SECRET = os.environ.get("SUPABASE_STACK_JWT_SECRET", "")

if not (STACK_URL and PUBLISHABLE_KEY and DB_URL):
    pytest.skip(
        "No Supabase stack configured (set SUPABASE_STACK_URL, SUPABASE_STACK_PUBLISHABLE_KEY and "
        "SUPABASE_STACK_DB_URL; see the module docstring).",
        allow_module_level=True,
    )

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
        )
    return IsolatedSettings(
        app_env=AppEnv.TEST,
        database_url=SecretStr(DB_URL),
        supabase_url=STACK_URL,
        supabase_jwt_mode=JwtMode.JWKS,
        db_pool_max_size=4,
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
