import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession

from shop import api


@pytest.mark.parametrize("secure", [False, True])
async def test_session_cookie_security_and_embedded_context(
    monkeypatch: pytest.MonkeyPatch, secure: bool
) -> None:
    monkeypatch.setattr(api.settings, "cookie_secure", secure)
    response = Response()
    await api.new_session(AsyncMock(spec=AsyncSession), response, uuid.uuid4())
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Path=/" in cookie
    if secure:
        assert cookie.startswith("__Host-catalog_session=")
        assert "SameSite=none" in cookie and "Secure" in cookie and "Partitioned" in cookie
    else:
        assert cookie.startswith("catalog_session=")
        assert "SameSite=lax" in cookie and "Secure" not in cookie and "Partitioned" not in cookie
