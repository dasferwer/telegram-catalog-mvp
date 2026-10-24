import os
import socket
import time
from collections.abc import AsyncIterator
from itertools import count
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shop.config import Settings
from shop.db import connect
from shop.models import Product
from shop.storage import Storage

_ids = count(time.time_ns() % 1_000_000_000_000)
SECRET = "local-test-webhook-secret"
ORIGIN = os.getenv("PUBLIC_ORIGIN", "http://localhost:8088")


def update_id() -> int:
    return next(_ids)


def replicas(service: str, port: int) -> list[str]:
    addresses = sorted(
        {x[4][0] for x in socket.getaddrinfo(service, port, type=socket.SOCK_STREAM)}
    )
    return [f"http://{ip}:{port}" for ip in addresses]


def update(
    *,
    text: str | None = None,
    caption: str | None = None,
    photo: bool = False,
    user_id: int = 42,
    file_id: str = "photo",
    size: int = 1024,
    album: bool = False,
    document: bool = False,
) -> dict[str, Any]:
    uid = update_id()
    message: dict[str, Any] = {
        "message_id": uid,
        "date": int(time.time()),
        "chat": {"id": user_id, "type": "private"},
        "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
    }
    if text is not None:
        message["text"] = text
    if caption is not None:
        message["caption"] = caption
    if photo:
        message["photo"] = [
            {
                "file_id": file_id,
                "file_unique_id": file_id,
                "width": 32,
                "height": 24,
                "file_size": size,
            }
        ]
    if album:
        message["media_group_id"] = "test-album"
    if document:
        message["document"] = {"file_id": "document", "file_unique_id": "doc"}
    return {"update_id": uid, "message": message}


async def webhook(client: httpx.AsyncClient, base: str, body: dict[str, Any]) -> httpx.Response:
    return await client.post(
        base + "/telegram/webhook",
        json=body,
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
        timeout=45,
    )


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=20) as value:
        yield value


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    if os.getenv("INTEGRATION") != "1":
        pytest.skip("Requires isolated PostgreSQL/MinIO Compose stack")
    engine, sessions = connect(Settings())
    async with sessions() as value:
        yield value
    await engine.dispose()


@pytest.fixture
async def storage(db: AsyncSession) -> AsyncIterator[Storage]:
    value = Storage(Settings())
    yield value
    await value.close()


@pytest.fixture
async def product(client: httpx.AsyncClient, db: AsyncSession) -> Product:
    bots = replicas("bot", 8001)
    assert len(bots) == 2
    assert (await webhook(client, bots[0], update(text="/create_product"))).status_code == 200
    body = update(photo=True, caption="Тестовый товар " + str(update_id()))
    assert (await webhook(client, bots[1], body)).status_code == 200
    result = await db.scalar(
        select(Product).where(Product.bot_id == 123456, Product.update_id == body["update_id"])
    )
    assert result is not None
    return result


class Browser:
    def __init__(self, client: httpx.AsyncClient, apis: list[str]) -> None:
        self.client = client
        self.apis = apis
        self.headers: dict[str, str] = {"Origin": ORIGIN}

    async def start(self) -> "Browser":
        response = await self.client.get(self.apis[0] + "/api/session", headers={"Cookie": ""})
        assert response.status_code == 200, response.text
        assert "HttpOnly" in response.headers["set-cookie"]
        self.headers["Cookie"] = response.headers["set-cookie"].split(";", 1)[0]
        self.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return self

    async def request(
        self, method: str, path: str, *, replica: int = 0, **kwargs: Any
    ) -> httpx.Response:
        headers = {**self.headers, **kwargs.pop("headers", {})}
        return await self.client.request(
            method, self.apis[replica] + path, headers=headers, **kwargs
        )
