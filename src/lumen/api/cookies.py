"""Session and CSRF cookies (spec 001 §2.3-2.4)."""

import hashlib
import hmac
from datetime import timedelta

from starlette.responses import Response


class CookieManager:
    def __init__(self, secret: bytes, *, secure: bool, max_age: timedelta) -> None:
        self._secret = secret
        self._secure = secure
        self._max_age = int(max_age.total_seconds())
        # __Host- makes browsers reject the cookie unless Secure, Path=/ and no
        # Domain, so it can't be planted or overwritten from a subdomain. The
        # prefix is only valid on Secure cookies.
        prefix = "__Host-" if secure else ""
        self.session_name = f"{prefix}lumen_session"
        self.csrf_name = f"{prefix}lumen_csrf"

    def csrf_token(self, session_token: str) -> str:
        """Derived from the session, so nothing is stored and it rotates with it."""
        return hmac.new(self._secret, session_token.encode(), hashlib.sha256).hexdigest()

    def csrf_matches(self, session_token: str, header: str | None) -> bool:
        return header is not None and hmac.compare_digest(self.csrf_token(session_token), header)

    def set(self, response: Response, session_token: str) -> None:
        # The CSRF cookie is readable by the frontend, which echoes it in X-CSRF-Token.
        for name, value, httponly in (
            (self.session_name, session_token, True),
            (self.csrf_name, self.csrf_token(session_token), False),
        ):
            response.set_cookie(
                name,
                value,
                max_age=self._max_age,
                path="/",
                secure=self._secure,
                httponly=httponly,
                samesite="strict",
            )

    def clear(self, response: Response) -> None:
        # Deletion must repeat Secure and Path=/, or browsers ignore it for __Host- cookies.
        for name, httponly in ((self.session_name, True), (self.csrf_name, False)):
            response.delete_cookie(
                name, path="/", secure=self._secure, httponly=httponly, samesite="strict"
            )
