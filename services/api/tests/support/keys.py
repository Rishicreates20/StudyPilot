"""Real signing keys and tokens for tests.

Nothing here fakes authentication: tokens are genuine signed JWTs and the API verifies them with
real cryptography against the matching public key, exactly as it does against Supabase's keys.
"""

import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from support.settings import TEST_AUDIENCE, TEST_ISSUER


@dataclass(frozen=True)
class SigningKey:
    kid: str
    alg: str
    private_key: Any
    public_jwk: dict[str, Any]


def make_ec_key(kid: str = "test-ec-1") -> SigningKey:
    private = ec.generate_private_key(ec.SECP256R1())
    jwk: dict[str, Any] = ECAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk.update({"kid": kid, "alg": "ES256", "use": "sig", "key_ops": ["verify"]})
    return SigningKey(kid=kid, alg="ES256", private_key=private, public_jwk=jwk)


def make_rsa_key(kid: str = "test-rsa-1") -> SigningKey:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk: dict[str, Any] = RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig", "key_ops": ["verify"]})
    return SigningKey(kid=kid, alg="RS256", private_key=private, public_jwk=jwk)


def jwks_document(*keys: SigningKey) -> dict[str, Any]:
    return {"keys": [key.public_jwk for key in keys]}


def static_jwks_fetcher(*keys: SigningKey) -> Callable[[], Awaitable[Mapping[str, Any]]]:
    async def fetch() -> Mapping[str, Any]:
        return jwks_document(*keys)

    return fetch


def build_claims(
    *,
    sub: uuid.UUID | str | None = None,
    role: str = "authenticated",
    audience: str | list[str] = TEST_AUDIENCE,
    issuer: str = TEST_ISSUER,
    expires_in: int = 3600,
    email: str | None = "learner@example.test",
    is_anonymous: bool = False,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + expires_in,
        "role": role,
        "aal": "aal1",
        "session_id": str(uuid.uuid4()),
        "is_anonymous": is_anonymous,
    }
    if sub is not None:
        claims["sub"] = str(sub)
    if email is not None:
        claims["email"] = email
    if extra:
        claims.update(extra)
    return claims


def sign_with_key(key: SigningKey, claims: Mapping[str, Any], *, kid: str | None = None) -> str:
    headers = {"kid": kid if kid is not None else key.kid}
    return jwt.encode(dict(claims), key.private_key, algorithm=key.alg, headers=headers)


def sign_hs256(secret: str, claims: Mapping[str, Any]) -> str:
    return jwt.encode(dict(claims), secret, algorithm="HS256")
