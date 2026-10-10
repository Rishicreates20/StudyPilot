#!/usr/bin/env python3
"""Export the settings of a running local Supabase stack to the later steps of a CI job.

Run after ``npx supabase start``. It reads ``npx supabase status -o json``, works out how the
stack signs access tokens (by creating one throwaway account and looking at the token's header,
never at its payload), and appends ``NAME=value`` lines to the file named by ``$GITHUB_ENV``.
Values that grant access are registered as masked secrets first. Run it locally to see the
variable *names* it would export: values are only written to ``$GITHUB_ENV``.

Standard library only, so it needs no installation.
"""

import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from typing import NoReturn

REQUIRED = {
    "api_url": ("API_URL",),
    "db_url": ("DB_URL",),
    "publishable_key": ("PUBLISHABLE_KEY", "ANON_KEY"),
    "jwt_secret": ("JWT_SECRET",),
}


def fail(message: str) -> NoReturn:
    print(f"::error title=Supabase stack::{message}")
    sys.exit(1)


def read_status() -> dict[str, str]:
    result = subprocess.run(
        [shutil.which("npx") or "npx", "--no-install", "supabase", "status", "-o", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"`supabase status` failed (exit {result.returncode}): {result.stderr.strip()[:300]}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        fail("`supabase status -o json` did not print JSON")
    if not isinstance(data, dict):
        fail("`supabase status -o json` printed something other than an object")
    return {str(key): str(value) for key, value in data.items()}


def pick(status: dict[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        if status.get(name):
            return status[name]
    return None


def signing_algorithm(api_url: str, publishable_key: str) -> str:
    """The `alg` in the header of a token this stack issues (creates one throwaway account)."""
    probe = {
        "email": f"probe-{uuid.uuid4().hex[:12]}@example.test",
        "password": secrets.token_urlsafe(18),
    }
    body = json.dumps(probe).encode()
    request = urllib.request.Request(
        f"{api_url}/auth/v1/signup",
        data=body,
        headers={"apikey": publishable_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - local stack
            token = json.load(response)["access_token"]
    except (urllib.error.URLError, KeyError, ValueError) as error:
        fail(
            "Could not create a probe account to learn the signing algorithm "
            f"({type(error).__name__}). Is email confirmation still enabled?"
        )
    header = token.split(".")[0]
    return json.loads(base64.urlsafe_b64decode(header + "=" * (-len(header) % 4)))["alg"]


def main() -> None:
    status = read_status()
    found = {key: pick(status, names) for key, names in REQUIRED.items()}
    missing = [key for key, value in found.items() if not value]
    if missing:
        fail(f"`supabase status` is missing {missing}; it printed these keys: {sorted(status)}")
    api_url, db_url, key, secret = (
        found["api_url"],
        found["db_url"],
        found["publishable_key"],
        found["jwt_secret"],
    )
    assert api_url and db_url and key and secret

    algorithm = signing_algorithm(api_url, key)
    mode = "hs256" if algorithm == "HS256" else "jwks"

    exports = {
        # For tests/supabase_stack
        "SUPABASE_STACK_URL": api_url,
        "SUPABASE_STACK_PUBLISHABLE_KEY": key,
        "SUPABASE_STACK_DB_URL": db_url,
        "SUPABASE_STACK_JWT_SECRET": secret,
        # For the API in the browser tests
        "DATABASE_URL": db_url,
        "SUPABASE_URL": api_url,
        "SUPABASE_JWT_MODE": mode,
        "SUPABASE_JWT_SECRET": secret if mode == "hs256" else "",
        # For building and running the web app
        "NEXT_PUBLIC_SUPABASE_URL": api_url,
        "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY": key,
        "NEXT_PUBLIC_API_BASE_URL": "http://127.0.0.1:8000",
    }

    env_file = os.environ.get("GITHUB_ENV")
    print(f"token signing algorithm: {algorithm} -> SUPABASE_JWT_MODE={mode}")
    print("exporting:", ", ".join(sorted(exports)))
    if not env_file:
        print("GITHUB_ENV is not set: nothing written (this is a dry run).")
        return
    for value in (db_url, secret):
        print(f"::add-mask::{value}")
    with open(env_file, "a", encoding="utf-8") as handle:
        for name, value in exports.items():
            handle.write(f"{name}={value}\n")


if __name__ == "__main__":
    main()
