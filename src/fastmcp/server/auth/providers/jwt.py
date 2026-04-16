"""TokenVerifier implementations for FastMCP."""

from __future__ import annotations

import contextlib
import json
import time
from dataclasses import dataclass
from typing import Any, cast

import httpx
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose.errors import JoseError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import AnyHttpUrl, SecretStr
from typing_extensions import TypedDict

from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.ssrf import SSRFError, SSRFFetchError, ssrf_safe_fetch
from fastmcp.utilities.auth import decode_jwt_header, parse_scopes
from fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


class JWKData(TypedDict, total=False):
    """JSON Web Key data structure."""

    kty: str  # Key type (e.g., "RSA") - required
    kid: str  # Key ID (optional but recommended)
    use: str  # Usage (e.g., "sig")
    alg: str  # Algorithm (e.g., "RS256")
    n: str  # Modulus (for RSA keys)
    e: str  # Exponent (for RSA keys)
    x5c: list[str]  # X.509 certificate chain (for JWKs)
    x5t: str  # X.509 certificate thumbprint (for JWKs)


class JWKSData(TypedDict):
    """JSON Web Key Set data structure."""

    keys: list[JWKData]


@dataclass(frozen=True, kw_only=True, repr=False)
class RSAKeyPair:
    """RSA key pair for JWT testing."""

    private_key: SecretStr
    public_key: str

    @classmethod
    def generate(cls) -> RSAKeyPair:
        """
        Generate an RSA key pair for testing.

        Returns:
            RSAKeyPair: Generated key pair
        """
        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # Serialize private key to PEM format
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        # Serialize public key to PEM format
        public_pem = (
            private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode("utf-8")
        )

        return cls(
            private_key=SecretStr(private_pem),
            public_key=public_pem,
        )

    def create_token(
        self,
        subject: str = "fastmcp-user",
        issuer: str = "https://fastmcp.example.com",
        audience: str | list[str] | None = None,
        scopes: list[str] | None = None,
        expires_in_seconds: int = 3600,
        additional_claims: dict[str, Any] | None = None,
        kid: str | None = None,
    ) -> str:
        """
        Generate a test JWT token for testing purposes.

        Args:
            subject: Subject claim (usually user ID)
            issuer: Issuer claim
            audience: Audience claim - can be a string or list of strings (optional)
            scopes: List of scopes to include
            expires_in_seconds: Token expiration time in seconds
            additional_claims: Any additional claims to include
            kid: Key ID to include in header
        """
        # Create header
        header = {"alg": "RS256"}
        if kid:
            header["kid"] = kid

        # Create payload
        payload: dict[str, str | int | list[str]] = {
            "sub": subject,
            "iss": issuer,
            "iat": int(time.time()),
            "exp": int(time.time()) + expires_in_seconds,
        }

        if audience:
            payload["aud"] = audience

        if scopes:
            payload["scope"] = " ".join(scopes)

        if additional_claims:
            payload.update(additional_claims)

        # Create JWT
        jwt_lib = JsonWebToken(["RS256"])
        token_bytes = jwt_lib.encode(
            header, payload, self.private_key.get_secret_value()
        )

        return token_bytes.decode("utf-8")


def _looks_like_pem_public_key(key: str | bytes) -> bool:
    """Return True when key text appears to be PEM-encoded asymmetric key material."""
    pass


class JWTVerifier(TokenVerifier):
    """
    JWT token verifier supporting both asymmetric (RSA/ECDSA) and symmetric (HMAC) algorithms.

    This verifier validates JWT tokens using various signing algorithms:
    - **Asymmetric algorithms** (RS256/384/512, ES256/384/512, PS256/384/512):
      Uses public/private key pairs. Ideal for external clients and services where
      only the authorization server has the private key.
    - **Symmetric algorithms** (HS256/384/512): Uses a shared secret for both
      signing and verification. Perfect for internal microservices and trusted
      environments where the secret can be securely shared.

    Use this when:
    - You have JWT tokens issued by an external service (asymmetric)
    - You need JWKS support for automatic key rotation (asymmetric)
    - You have internal microservices sharing a secret key (symmetric)
    - Your tokens contain standard OAuth scopes and claims
    """

    def __init__(
        self,
        *,
        public_key: str | bytes | None = None,
        jwks_uri: str | None = None,
        issuer: str | list[str] | None = None,
        audience: str | list[str] | None = None,
        algorithm: str | None = None,
        required_scopes: list[str] | None = None,
        base_url: AnyHttpUrl | str | None = None,
        ssrf_safe: bool = False,
        http_client: httpx.AsyncClient | None = None,
    ):
        """
        Initialize a JWTVerifier configured to validate JWTs using either a static key or a JWKS endpoint.

        Parameters:
            public_key: PEM-encoded public key for asymmetric algorithms or shared secret for symmetric algorithms.
            jwks_uri: URI to fetch a JSON Web Key Set; used when verifying tokens with remote JWKS.
            issuer: Expected issuer claim value or list of allowed issuer values.
            audience: Expected audience claim value or list of allowed audience values.
            algorithm: JWT signing algorithm to accept (default: "RS256"). Supported: HS256/384/512, RS256/384/512, ES256/384/512, PS256/384/512.
            required_scopes: Scopes that must be present in validated tokens.
            base_url: Base URL passed to the parent TokenVerifier.
            ssrf_safe: If True, JWKS fetches use SSRF protection (HTTPS-only,
                public IPs, DNS pinning). Enable when the JWKS URI comes from
                untrusted input (e.g. CIMD documents). Defaults to False so
                operator-configured JWKS URIs (including localhost) work normally.
            http_client: Optional httpx.AsyncClient for connection pooling. When provided,
                the client is reused for JWKS fetches and the caller is responsible for
                its lifecycle. When None (default), a fresh client is created per fetch.
                Cannot be used with ssrf_safe=True.

        Raises:
            ValueError: If neither or both of `public_key` and `jwks_uri` are provided,
                if `algorithm` is unsupported, or if `http_client` is provided with `ssrf_safe=True`.
        """
        if not public_key and not jwks_uri:
            raise ValueError("Either public_key or jwks_uri must be provided")

        if public_key and jwks_uri:
            raise ValueError("Provide either public_key or jwks_uri, not both")

        # Only enforce ssrf_safe/http_client exclusivity when JWKS fetching is used
        if jwks_uri and ssrf_safe and http_client is not None:
            raise ValueError(
                "http_client cannot be used with ssrf_safe=True; "
                "SSRF-safe mode requires its own hardened transport"
            )

        algorithm = algorithm or "RS256"
        if algorithm not in {
            "HS256",
            "HS384",
            "HS512",
            "RS256",
            "RS384",
            "RS512",
            "ES256",
            "ES384",
            "ES512",
            "PS256",
            "PS384",
            "PS512",
        }:
            raise ValueError(f"Unsupported algorithm: {algorithm}.")

        if algorithm.startswith("HS"):
            if jwks_uri:
                raise ValueError(
                    "Symmetric HS* algorithms cannot be used with jwks_uri; "
                    "configure a shared secret via public_key instead."
                )
            if public_key and _looks_like_pem_public_key(public_key):
                raise ValueError(
                    "Symmetric HS* algorithms require a shared secret, not a public key."
                )

        # Parse scopes if provided as string
        parsed_required_scopes = (
            parse_scopes(required_scopes) if required_scopes is not None else None
        )

        # Initialize parent TokenVerifier
        super().__init__(
            base_url=base_url,
            required_scopes=parsed_required_scopes,
        )

        self.algorithm = algorithm
        self.issuer = issuer
        self.audience = audience
        self.public_key = public_key
        self.jwks_uri = jwks_uri
        self.ssrf_safe = ssrf_safe
        self._http_client = http_client
        self.jwt = JsonWebToken([self.algorithm])
        self.logger = get_logger(__name__)

        # Simple JWKS cache
        self._jwks_cache: dict[str, str] = {}
        self._jwks_cache_time: float = 0
        self._cache_ttl = 3600  # 1 hour

    async def _get_verification_key(self, token: str) -> str | bytes:
        """Get the verification key for the token."""
        pass

    async def _get_jwks_key(self, kid: str | None) -> str:
        """Fetch key from JWKS with simple caching and SSRF protection."""
        pass

    async def _fetch_jwks(self) -> dict[str, Any]:
        """Fetch JWKS data, using SSRF-safe or standard fetch based on config."""
        pass

    def _extract_scopes(self, claims: dict[str, Any]) -> list[str]:
        """
        Extract scopes from JWT claims. Supports both 'scope' and 'scp'
        claims.

        Checks the `scope` claim first (standard OAuth2 claim), then the `scp`
        claim (used by some Identity Providers).
        """
        pass

    async def load_access_token(self, token: str) -> AccessToken | None:
        """
        Validate a JWT bearer token and return an AccessToken when the token is valid.

        Parameters:
            token (str): The JWT bearer token string to validate.

        Returns:
            AccessToken | None: An AccessToken populated from token claims if the token is valid; `None` if the token is expired, has an invalid signature or format, fails issuer/audience/scope validation, or any other validation error occurs.
        """
        pass

    async def verify_token(self, token: str) -> AccessToken | None:
        """
        Verify a bearer token and return access info if valid.

        This method implements the TokenVerifier protocol by delegating
        to our existing load_access_token method.

        Args:
            token: The JWT token string to validate

        Returns:
            AccessToken object if valid, None if invalid or expired
        """
        pass


class StaticTokenVerifier(TokenVerifier):
    """
    Simple static token verifier for testing and development.

    This verifier validates tokens against a predefined dictionary of valid token
    strings and their associated claims. When a token string matches a key in the
    dictionary, the verifier returns the corresponding claims as if the token was
    validated by a real authorization server.

    Use this when:
    - You're developing or testing locally without a real OAuth server
    - You need predictable tokens for automated testing
    - You want to simulate different users/scopes without complex setup
    - You're prototyping and need simple API key-style authentication

    WARNING: Never use this in production - tokens are stored in plain text!
    """

    def __init__(
        self,
        tokens: dict[str, dict[str, Any]],
        required_scopes: list[str] | None = None,
    ):
        """
        Initialize the static token verifier.

        Args:
            tokens: Dict mapping token strings to token metadata
                   Each token should have: client_id, scopes, expires_at (optional)
            required_scopes: Required scopes for all tokens
        """
        super().__init__(required_scopes=required_scopes)
        self.tokens = tokens

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify token against static token dictionary."""
        pass
