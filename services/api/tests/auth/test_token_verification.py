"""Access-token verification: the gate in front of every protected operation.

Every token here is a genuine signed JWT. The tests prove what the verifier refuses as much as
what it accepts, including the classic JWT attacks (none, algorithm confusion, wrong key).
"""

import base64
import json
import time
import uuid
from typing import Any, cast

import jwt
import pytest

from app.core.config import JwtMode
from app.core.security import JwksCache, Principal, TokenVerificationError, TokenVerifier
from support.keys import (
    SigningKey,
    build_claims,
    make_ec_key,
    make_rsa_key,
    sign_hs256,
    sign_with_key,
    static_jwks_fetcher,
)
from support.settings import TEST_AUDIENCE, TEST_ISSUER

pytestmark = pytest.mark.anyio

HS256_SECRET = "a-local-development-jwt-secret-of-sufficient-length"  # noqa: S105 - test value


@pytest.fixture(scope="module")
def ec_key() -> SigningKey:
    return make_ec_key("ec-key")


@pytest.fixture(scope="module")
def rsa_key() -> SigningKey:
    return make_rsa_key("rsa-key")


def jwks_verifier(*keys: SigningKey, leeway: int = 0) -> TokenVerifier:
    return TokenVerifier(
        mode=JwtMode.JWKS,
        audience=TEST_AUDIENCE,
        issuer=TEST_ISSUER,
        leeway_seconds=leeway,
        jwks=JwksCache(static_jwks_fetcher(*keys)),
    )


def hs256_verifier(secret: str = HS256_SECRET) -> TokenVerifier:
    return TokenVerifier(
        mode=JwtMode.HS256,
        audience=TEST_AUDIENCE,
        issuer=TEST_ISSUER,
        leeway_seconds=0,
        hs256_secret=secret,
    )


async def rejection(verifier: TokenVerifier, token: str) -> TokenVerificationError:
    with pytest.raises(TokenVerificationError) as caught:
        await verifier.verify(token)
    return caught.value


# --- Accepted tokens -------------------------------------------------------------------------


async def test_a_valid_es256_token_yields_the_verified_principal(ec_key: SigningKey) -> None:
    user_id = uuid.uuid4()
    token = sign_with_key(ec_key, build_claims(sub=user_id, email="ada@example.test"))

    principal = await jwks_verifier(ec_key).verify(token)

    assert isinstance(principal, Principal)
    assert principal.user_id == user_id
    assert principal.email == "ada@example.test"
    assert principal.claims["sub"] == str(user_id)
    assert principal.claims["role"] == "authenticated"


async def test_a_valid_rs256_token_is_accepted(rsa_key: SigningKey) -> None:
    user_id = uuid.uuid4()

    principal = await jwks_verifier(rsa_key).verify(
        sign_with_key(rsa_key, build_claims(sub=user_id))
    )

    assert principal.user_id == user_id


async def test_the_right_key_is_chosen_by_kid_when_several_are_published(
    ec_key: SigningKey, rsa_key: SigningKey
) -> None:
    verifier = jwks_verifier(ec_key, rsa_key)
    user_id = uuid.uuid4()

    assert (await verifier.verify(sign_with_key(rsa_key, build_claims(sub=user_id)))).user_id == (
        user_id
    )
    assert (await verifier.verify(sign_with_key(ec_key, build_claims(sub=user_id)))).user_id == (
        user_id
    )


async def test_a_valid_hs256_token_is_accepted_in_hs256_mode() -> None:
    user_id = uuid.uuid4()

    principal = await hs256_verifier().verify(sign_hs256(HS256_SECRET, build_claims(sub=user_id)))

    assert principal.user_id == user_id


async def test_an_uppercase_subject_is_normalised_to_the_canonical_form(ec_key: SigningKey) -> None:
    user_id = uuid.uuid4()
    claims = build_claims(sub=str(user_id).upper())

    principal = await jwks_verifier(ec_key).verify(sign_with_key(ec_key, claims))

    assert principal.user_id == user_id
    assert principal.claims["sub"] == str(user_id)


async def test_a_token_that_expired_moments_ago_is_accepted_within_the_clock_leeway(
    ec_key: SigningKey,
) -> None:
    token = sign_with_key(ec_key, build_claims(sub=uuid.uuid4(), expires_in=-5))

    await jwks_verifier(ec_key, leeway=10).verify(token)


# --- Expired and invalid tokens --------------------------------------------------------------


async def test_an_expired_token_is_reported_as_expired(ec_key: SigningKey) -> None:
    token = sign_with_key(ec_key, build_claims(sub=uuid.uuid4(), expires_in=-60))

    error = await rejection(jwks_verifier(ec_key), token)

    assert (error.code, error.reason) == ("TOKEN_EXPIRED", "expired")


async def test_an_hs256_token_that_expired_is_reported_as_expired() -> None:
    token = sign_hs256(HS256_SECRET, build_claims(sub=uuid.uuid4(), expires_in=-60))

    assert (await rejection(hs256_verifier(), token)).code == "TOKEN_EXPIRED"


@pytest.mark.parametrize(
    "garbage", ["", "not-a-jwt", "a.b.c", "eyJhbGciOiJIUzI1NiJ9.e30.", "x" * 5000]
)
async def test_malformed_tokens_are_rejected(ec_key: SigningKey, garbage: str) -> None:
    error = await rejection(jwks_verifier(ec_key), garbage)

    assert error.code == "INVALID_TOKEN"


async def test_a_token_signed_by_a_different_key_is_rejected(ec_key: SigningKey) -> None:
    attacker = make_ec_key("ec-key")  # same kid, different private key
    token = sign_with_key(attacker, build_claims(sub=uuid.uuid4()))

    error = await rejection(jwks_verifier(ec_key), token)

    assert error.reason == "bad_signature"


async def test_a_tampered_payload_is_rejected(ec_key: SigningKey) -> None:
    token = sign_with_key(ec_key, build_claims(sub=uuid.uuid4()))
    header, _payload, signature = token.split(".")
    forged_claims = build_claims(sub=uuid.uuid4(), email="victim@example.test")
    forged_payload = (
        base64.urlsafe_b64encode(json.dumps(forged_claims).encode()).rstrip(b"=").decode()
    )

    error = await rejection(jwks_verifier(ec_key), f"{header}.{forged_payload}.{signature}")

    assert error.reason == "bad_signature"


async def test_a_token_for_another_project_is_rejected_by_issuer(ec_key: SigningKey) -> None:
    claims = build_claims(sub=uuid.uuid4(), issuer="https://other-project.supabase.co/auth/v1")

    error = await rejection(jwks_verifier(ec_key), sign_with_key(ec_key, claims))

    assert error.reason == "wrong_issuer"


@pytest.mark.parametrize("audience", ["anon", "service_role", "something-else", ["other"]])
async def test_a_token_for_a_different_audience_is_rejected(
    ec_key: SigningKey, audience: str | list[str]
) -> None:
    claims = build_claims(sub=uuid.uuid4(), audience=audience)

    error = await rejection(jwks_verifier(ec_key), sign_with_key(ec_key, claims))

    assert error.reason == "wrong_audience"


@pytest.mark.parametrize("claim", ["exp", "sub", "aud", "iss"])
async def test_a_token_missing_a_required_claim_is_rejected(ec_key: SigningKey, claim: str) -> None:
    claims = build_claims(sub=uuid.uuid4())
    del claims[claim]

    error = await rejection(jwks_verifier(ec_key), sign_with_key(ec_key, claims))

    assert error.reason == f"missing_claim:{claim}"


# --- The classic JWT attacks -----------------------------------------------------------------


async def test_alg_none_is_rejected(ec_key: SigningKey) -> None:
    unsigned = jwt.encode(
        build_claims(sub=uuid.uuid4()),
        key=cast(Any, None),  # "none" means no key; the typing stubs do not model that
        algorithm="none",
        headers={"kid": ec_key.kid},
    )

    error = await rejection(jwks_verifier(ec_key), unsigned)

    assert error.reason == "unexpected_algorithm"


async def test_an_hs256_token_is_refused_when_asymmetric_keys_are_expected(
    ec_key: SigningKey,
) -> None:
    """Algorithm confusion: forging HS256 with a publicly known value must never verify."""
    public_x = str(ec_key.public_jwk["x"])
    forged = jwt.encode(
        build_claims(sub=uuid.uuid4()),
        key=public_x * 2,
        algorithm="HS256",
        headers={"kid": ec_key.kid},
    )

    error = await rejection(jwks_verifier(ec_key), forged)

    assert error.reason == "unexpected_algorithm"


async def test_an_asymmetric_token_is_refused_in_hs256_mode(ec_key: SigningKey) -> None:
    token = sign_with_key(ec_key, build_claims(sub=uuid.uuid4()))

    assert (await rejection(hs256_verifier(), token)).reason == "unexpected_algorithm"


async def test_hs256_mode_rejects_a_token_signed_with_the_wrong_secret() -> None:
    token = sign_hs256("another-secret-that-is-also-long-enough-ok", build_claims(sub=uuid.uuid4()))

    assert (await rejection(hs256_verifier(), token)).reason == "bad_signature"


async def test_a_token_whose_header_algorithm_differs_from_the_published_key_is_rejected(
    ec_key: SigningKey, rsa_key: SigningKey
) -> None:
    """RS256 claimed for a kid that is published as an EC key."""
    token = sign_with_key(rsa_key, build_claims(sub=uuid.uuid4()), kid=ec_key.kid)

    error = await rejection(jwks_verifier(ec_key, rsa_key), token)

    assert error.reason == "algorithm_mismatch"


async def test_a_token_without_a_kid_is_rejected_in_jwks_mode(ec_key: SigningKey) -> None:
    token = jwt.encode(build_claims(sub=uuid.uuid4()), ec_key.private_key, algorithm="ES256")

    assert (await rejection(jwks_verifier(ec_key), token)).reason == "missing_kid"


async def test_a_token_naming_an_unpublished_key_is_rejected(ec_key: SigningKey) -> None:
    stranger = make_ec_key("never-published")
    token = sign_with_key(stranger, build_claims(sub=uuid.uuid4()))

    assert (await rejection(jwks_verifier(ec_key), token)).reason == "unknown_kid"


# --- Tokens that are valid JWTs but are not a signed-in user ---------------------------------


async def test_the_anon_api_key_shape_is_not_a_user(ec_key: SigningKey) -> None:
    """Supabase's anon key is a JWT with role=anon, no sub and a different audience."""
    claims = build_claims(sub=None, role="anon", audience="anon", email=None)

    assert (await rejection(jwks_verifier(ec_key), sign_with_key(ec_key, claims))).code == (
        "INVALID_TOKEN"
    )


async def test_a_service_role_token_is_not_a_user(ec_key: SigningKey) -> None:
    claims = build_claims(sub=uuid.uuid4(), role="service_role")

    error = await rejection(jwks_verifier(ec_key), sign_with_key(ec_key, claims))

    assert error.reason == "wrong_role"


async def test_an_anonymous_sign_in_is_not_accepted(ec_key: SigningKey) -> None:
    claims = build_claims(sub=uuid.uuid4(), is_anonymous=True)

    error = await rejection(jwks_verifier(ec_key), sign_with_key(ec_key, claims))

    assert error.reason == "anonymous_user"


@pytest.mark.parametrize(
    "subject",
    ["not-a-uuid", "12345", "{" + str(uuid.uuid4()) + "}", "urn:uuid:" + str(uuid.uuid4()), ""],
)
async def test_a_subject_that_is_not_a_canonical_uuid_is_rejected(
    ec_key: SigningKey, subject: str
) -> None:
    claims: dict[str, Any] = build_claims(sub=subject)

    error = await rejection(jwks_verifier(ec_key), sign_with_key(ec_key, claims))

    assert error.code == "INVALID_TOKEN"


async def test_the_verifier_does_not_accept_a_token_issued_in_the_future(
    ec_key: SigningKey,
) -> None:
    claims = build_claims(sub=uuid.uuid4(), extra={"nbf": int(time.time()) + 3600})

    error = await rejection(jwks_verifier(ec_key), sign_with_key(ec_key, claims))

    assert error.code == "INVALID_TOKEN"
