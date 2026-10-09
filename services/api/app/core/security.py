"""Verification of Supabase access tokens (JWTs) and the FastAPI dependency that requires them.

Trust model
-----------
The caller's identity comes only from a token whose signature, issuer, audience and expiry have
been verified here. Nothing the browser sends in a body, query string or custom header is ever
treated as proof of who the caller is.

* ``jwks`` mode (hosted projects with asymmetric signing keys): the token must be signed with
  ES256 or RS256 by a key published at the project's JWKS URL. HS256 and ``none`` are refused,
  which closes the classic algorithm-confusion attack.
* ``hs256`` mode (legacy projects and the local Supabase CLI stack): the token must be HS256
  signed with the project's JWT secret.

Tokens are never logged. Rejections log a short reason category only.
"""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Final, cast

import httpx2
import jwt
import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWK

from app.core.config import JwtMode, Settings
from app.core.errors import AuthenticationError, ServiceUnavailableError

log = structlog.get_logger("app.security")

JwksFetcher = Callable[[], Awaitable[Mapping[str, Any]]]

# Algorithms Supabase signing keys use today (EdDSA is "coming soon" in their docs).
ASYMMETRIC_ALGORITHMS: Final = ("ES256", "RS256")
_REQUIRED_CLAIMS: Final = ["exp", "sub", "aud", "iss"]


class TokenVerificationError(Exception):
    """The token is not acceptable. ``code`` is client-safe; ``reason`` is for logs only."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


class AuthUnavailableError(Exception):
    """Verification could not be attempted (for example the signing keys cannot be fetched)."""


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller, derived exclusively from a verified token."""

    user_id: uuid.UUID
    email: str | None
    # The verified claims. Passed to PostgreSQL as request.jwt.claims so RLS policies can use them.
    claims: Mapping[str, Any]


class JwksCache:
    """Signing keys fetched from the project's JWKS URL.

    * Keys are refreshed after ``ttl`` seconds (Supabase's edge caches the endpoint for 10 minutes
      and advises against caching longer).
    * A token naming an unknown ``kid`` triggers at most one refetch per ``refetch_cooldown``
      seconds, so a flood of forged tokens cannot be turned into a flood of requests to Supabase.
    * If a refresh fails, keys already held keep working (stale-if-error) so a brief Supabase
      outage does not log everyone out.
    """

    def __init__(
        self,
        fetch: JwksFetcher,
        *,
        ttl: float = 600.0,
        refetch_cooldown: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch = fetch
        self._ttl = ttl
        self._cooldown = refetch_cooldown
        self._clock = clock
        self._keys: dict[str, PyJWK] = {}
        self._loaded_at: float | None = None
        self._last_attempt: float | None = None
        self._lock = asyncio.Lock()

    def _is_fresh(self, now: float) -> bool:
        return self._loaded_at is not None and now - self._loaded_at < self._ttl

    def _may_refetch_for_unknown_kid(self, now: float) -> bool:
        return self._last_attempt is None or now - self._last_attempt >= self._cooldown

    async def get_key(self, kid: str) -> PyJWK | None:
        now = self._clock()
        if self._is_fresh(now) and kid in self._keys:
            return self._keys[kid]
        if not self._is_fresh(now) or self._may_refetch_for_unknown_kid(now):
            await self._refresh()
        return self._keys.get(kid)

    async def _refresh(self) -> None:
        async with self._lock:
            now = self._clock()
            # Another task may have just refreshed (or failed to) while this one waited.
            if self._last_attempt is not None and now - self._last_attempt < 1.0:
                if not self._keys:
                    raise AuthUnavailableError
                return
            self._last_attempt = now
            try:
                document = await self._fetch()
            except Exception as exc:
                if self._keys:
                    log.warning(
                        "auth.jwks_refresh_failed_using_cached", error_type=type(exc).__name__
                    )
                    return
                log.error("auth.jwks_unavailable", error_type=type(exc).__name__)
                raise AuthUnavailableError from exc
            self._keys = self._parse(document)
            self._loaded_at = self._clock()

    @staticmethod
    def _parse(document: Mapping[str, Any]) -> dict[str, PyJWK]:
        keys: dict[str, PyJWK] = {}
        raw_keys = document.get("keys")
        if not isinstance(raw_keys, list):
            return keys
        for candidate in cast(list[object], raw_keys):
            if not isinstance(candidate, dict):
                continue
            raw = cast(dict[str, Any], candidate)
            kid = raw.get("kid")
            if not isinstance(kid, str) or not kid:
                continue
            try:
                keys[kid] = PyJWK(raw)
            except jwt.PyJWTError, ValueError, KeyError, TypeError:
                log.warning("auth.jwks_key_skipped")
        return keys


class HttpJwksFetcher:
    """Fetches the JWKS document over HTTP (Supabase: ``/auth/v1/.well-known/jwks.json``)."""

    def __init__(self, client: httpx2.AsyncClient, url: str) -> None:
        self._client = client
        self._url = url

    async def __call__(self) -> Mapping[str, Any]:
        response = await self._client.get(self._url, headers={"Accept": "application/json"})
        response.raise_for_status()
        document = response.json()
        if not isinstance(document, dict) or not isinstance(document.get("keys"), list):  # pyright: ignore[reportUnknownMemberType]
            raise ValueError("unexpected JWKS payload")
        return document  # pyright: ignore[reportUnknownVariableType]


class TokenVerifier:
    def __init__(
        self,
        *,
        mode: JwtMode,
        audience: str,
        issuer: str,
        leeway_seconds: int,
        hs256_secret: str | None = None,
        jwks: JwksCache | None = None,
    ) -> None:
        if mode is JwtMode.HS256 and not hs256_secret:
            raise ValueError("hs256 mode requires a secret")
        if mode is JwtMode.JWKS and jwks is None:
            raise ValueError("jwks mode requires a key cache")
        self._mode = mode
        self._audience = audience
        self._issuer = issuer
        self._leeway = leeway_seconds
        self._secret = hs256_secret
        self._jwks = jwks

    @classmethod
    def from_settings(
        cls, settings: Settings, *, fetcher: JwksFetcher | None
    ) -> TokenVerifier | None:
        """Build the verifier, or None when auth is not configured (tests without Supabase)."""
        issuer = settings.jwt_issuer
        if issuer is None:
            return None
        if settings.supabase_jwt_mode is JwtMode.HS256:
            secret = settings.supabase_jwt_secret
            return cls(
                mode=JwtMode.HS256,
                audience=settings.supabase_jwt_audience,
                issuer=issuer,
                leeway_seconds=settings.jwt_leeway_seconds,
                hs256_secret=secret.get_secret_value() if secret else None,
            )
        if fetcher is None:
            return None
        return cls(
            mode=JwtMode.JWKS,
            audience=settings.supabase_jwt_audience,
            issuer=issuer,
            leeway_seconds=settings.jwt_leeway_seconds,
            jwks=JwksCache(fetcher),
        )

    async def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise TokenVerificationError("INVALID_TOKEN", "malformed") from exc

        algorithm = header.get("alg")
        key: Any
        if self._mode is JwtMode.HS256:
            if algorithm != "HS256":
                raise TokenVerificationError("INVALID_TOKEN", "unexpected_algorithm")
            key = self._secret
        else:
            if algorithm not in ASYMMETRIC_ALGORITHMS:
                # Rejects "none" and HS256 (an attacker "signing" with the public key).
                raise TokenVerificationError("INVALID_TOKEN", "unexpected_algorithm")
            kid = header.get("kid")
            if not isinstance(kid, str) or not kid:
                raise TokenVerificationError("INVALID_TOKEN", "missing_kid")
            assert self._jwks is not None  # guaranteed by __init__  # noqa: S101
            jwk = await self._jwks.get_key(kid)
            if jwk is None:
                raise TokenVerificationError("INVALID_TOKEN", "unknown_kid")
            if getattr(jwk, "algorithm_name", algorithm) != algorithm:
                raise TokenVerificationError("INVALID_TOKEN", "algorithm_mismatch")
            key = jwk.key

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=[str(algorithm)],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": _REQUIRED_CLAIMS},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenVerificationError("TOKEN_EXPIRED", "expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise TokenVerificationError("INVALID_TOKEN", "wrong_audience") from exc
        except jwt.InvalidIssuerError as exc:
            raise TokenVerificationError("INVALID_TOKEN", "wrong_issuer") from exc
        except jwt.MissingRequiredClaimError as exc:
            raise TokenVerificationError("INVALID_TOKEN", f"missing_claim:{exc.claim}") from exc
        except jwt.InvalidSignatureError as exc:
            raise TokenVerificationError("INVALID_TOKEN", "bad_signature") from exc
        except jwt.PyJWTError as exc:
            raise TokenVerificationError("INVALID_TOKEN", "invalid") from exc

        return self._principal_from(claims)

    @staticmethod
    def _principal_from(claims: dict[str, Any]) -> Principal:
        subject = str(claims.get("sub", ""))
        try:
            user_id = uuid.UUID(subject)
        except ValueError as exc:
            raise TokenVerificationError("INVALID_TOKEN", "bad_subject") from exc
        if str(user_id) != subject.lower():
            # Only the canonical form, so every layer agrees on who the user is.
            raise TokenVerificationError("INVALID_TOKEN", "bad_subject")
        # The anon and service_role API keys are valid JWTs too; neither is a signed-in user.
        if claims.get("role") != "authenticated":
            raise TokenVerificationError("INVALID_TOKEN", "wrong_role")
        if claims.get("is_anonymous") is True:
            raise TokenVerificationError("INVALID_TOKEN", "anonymous_user")
        email = claims.get("email")
        return Principal(
            user_id=user_id,
            email=email if isinstance(email, str) else None,
            claims={**claims, "sub": str(user_id)},
        )


_bearer = HTTPBearer(auto_error=False)

_BEARER_INVALID = 'Bearer error="invalid_token"'
_BEARER_EXPIRED = 'Bearer error="invalid_token", error_description="The access token expired"'


async def get_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    """Require a valid bearer token. Every ``/v1`` route depends on this (see the v1 router)."""
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        log.info("auth.rejected", reason="missing_credentials")
        raise AuthenticationError("Authentication required.", code="UNAUTHENTICATED")

    verifier: TokenVerifier | None = request.app.state.token_verifier
    if verifier is None:
        log.error("auth.not_configured")
        raise ServiceUnavailableError(
            "Authentication is not configured on this server.", code="AUTH_NOT_CONFIGURED"
        )

    try:
        principal = await verifier.verify(credentials.credentials)
    except TokenVerificationError as exc:
        log.warning("auth.rejected", reason=exc.reason)
        if exc.code == "TOKEN_EXPIRED":
            raise AuthenticationError(
                "Your session has expired. Sign in again.",
                code="TOKEN_EXPIRED",
                www_authenticate=_BEARER_EXPIRED,
            ) from None
        raise AuthenticationError(
            "The access token is not valid.", code="INVALID_TOKEN", www_authenticate=_BEARER_INVALID
        ) from None
    except AuthUnavailableError:
        raise ServiceUnavailableError(
            "Authentication is temporarily unavailable. Please try again shortly.",
            code="AUTH_UNAVAILABLE",
        ) from None

    structlog.contextvars.bind_contextvars(user_id=str(principal.user_id))
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
