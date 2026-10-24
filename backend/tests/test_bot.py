import asyncio
import json

import httpx
import pytest
from conftest import ORIGIN, replicas, update, webhook
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shop.models import AdminState, BotUpdate, Product
from shop.storage import Storage


async def test_exact_greeting_and_permissions(client: httpx.AsyncClient, db: AsyncSession) -> None:
    bot = replicas("bot", 8001)[0]
    for value in ["/start", "Привет"]:
        assert (await webhook(client, bot, update(text=value, user_id=7))).status_code == 200
        message = (await client.get("http://telegram-test:8081/messages")).json()[-1]
        assert message["text"] == "У меня есть товар"
        keyboard = json.loads(message["reply_markup"])["inline_keyboard"]
        assert keyboard == [[{"text": "Открыть каталог", "web_app": {"url": ORIGIN}}]]
    forbidden = update(text="/create_product", user_id=7)
    assert (await webhook(client, bot, forbidden)).status_code == 200
    assert (await client.get("http://telegram-test:8081/messages")).json()[-1][
        "text"
    ] == "Доступ запрещён"
    assert (
        await db.scalar(
            select(func.count())
            .select_from(Product)
            .where(Product.update_id == forbidden["update_id"])
        )
        == 0
    )
    assert (
        await client.post(bot + "/telegram/webhook", json=update(text="/start"))
    ).status_code == 403
    assert (
        await client.post(replicas("api", 8000)[0] + "/api/products", json={"name": "hack"})
    ).status_code == 405


async def test_create_button_checks_sender_and_survives_callback_replay(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    bots = replicas("bot", 8001)
    for user_id in (7, 42):
        message = update(text="/start", user_id=user_id)
        assert (await webhook(client, bots[0], message)).status_code == 200
        reply = (await client.get("http://telegram-test:8081/messages")).json()[-1]
        buttons = json.loads(reply["reply_markup"])["inline_keyboard"]
        if user_id == 42:
            assert buttons[1] == [{"text": "Создать товар", "callback_data": "create_product"}]
        callback = {
            "update_id": update()["update_id"],
            "callback_query": {
                "id": str(message["update_id"]),
                "from": message["message"]["from"],
                "chat_instance": "test",
                "data": "create_product",
                "message": message["message"]
                | {"from": {"id": 123456, "is_bot": True, "first_name": "Bot"}},
            },
        }
        results = await asyncio.gather(*(webhook(client, base, callback) for base in bots))
        assert {r.status_code for r in results} == {200}
        reply = (await client.get("http://telegram-test:8081/messages")).json()[-1]
        assert (reply["text"] == "Доступ запрещён") == (user_id == 7)
        if user_id == 42:
            assert "reply_markup" not in reply
        db.expire_all()
        state = await db.get(AdminState, (123456, user_id))
        assert (state is not None and state.waiting) == (user_id == 42)


async def test_concurrent_duplicate_two_replicas(
    client: httpx.AsyncClient, db: AsyncSession, storage: Storage
) -> None:
    bots = replicas("bot", 8001)
    assert len(bots) == 2
    first = await webhook(client, bots[0], update(text="Создать товар"))
    prompt = (await client.get("http://telegram-test:8081/messages")).json()[-1]
    assert "reply_markup" not in prompt
    body = update(photo=True, caption="  Один товар  ")
    responses = await asyncio.gather(*(webhook(client, bots[i % 2], body) for i in range(6)))
    assert {r.status_code for r in responses} == {200}
    assert (
        len({first.headers["x-instance-id"], *(r.headers["x-instance-id"] for r in responses)}) == 2
    )
    rows = (await db.scalars(select(Product).where(Product.update_id == body["update_id"]))).all()
    assert len(rows) == 1 and rows[0].name == "Один товар"
    assert (await storage.read(rows[0].object_key)).startswith(b"\xff\xd8")
    state = await db.get(AdminState, (123456, 42))
    assert state and not state.waiting
    receipt = await db.get(BotUpdate, (123456, body["update_id"]))
    assert receipt and receipt.delivered
    reply = (await client.get("http://telegram-test:8081/messages")).json()[-1]
    assert reply["text"].startswith("Товар создан:")
    buttons = json.loads(reply["reply_markup"])["inline_keyboard"]
    assert [row[0]["text"] for row in buttons] == ["Открыть каталог", "Создать товар"]
    assert (await webhook(client, bots[1], body)).status_code == 200
    print("bot replicas:", sorted({r.headers["x-instance-id"] for r in responses}))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"photo": True},
        {"text": "Название"},
        {"document": True, "caption": "Название"},
        {"photo": True, "caption": " "},
        {"photo": True, "caption": "x" * 201},
        {"photo": True, "caption": "Альбом", "album": True},
        {"photo": True, "caption": "Большой", "size": 6 * 1024 * 1024},
        {"photo": True, "caption": "Недопустимый", "file_id": "invalid"},
        {"photo": True, "caption": "Скрытый размер", "file_id": "oversized"},
    ],
)
async def test_invalid_message_keeps_dialog(
    client: httpx.AsyncClient, db: AsyncSession, kwargs: dict[str, object]
) -> None:
    bot = replicas("bot", 8001)[0]
    assert (await webhook(client, bot, update(text="/create_product"))).status_code == 200
    prompt = (await client.get("http://telegram-test:8081/messages")).json()[-1]
    assert prompt["text"] == (
        "Отправьте фотографию и название в подписи одним сообщением "
        "(до 200 символов, JPEG/PNG до 5 МиБ)."
    )
    assert "reply_markup" not in prompt
    body = update(**kwargs)
    assert (await webhook(client, bot, body)).status_code == 200
    correction = (await client.get("http://telegram-test:8081/messages")).json()[-1]
    assert "reply_markup" not in correction
    assert (
        await db.scalar(
            select(func.count()).select_from(Product).where(Product.update_id == body["update_id"])
        )
        == 0
    )
    state = await db.get(AdminState, (123456, 42))
    assert state and state.waiting


async def test_reply_failure_preserves_commit_and_retries(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    bots = replicas("bot", 8001)
    assert (await webhook(client, bots[0], update(text="/create_product"))).status_code == 200
    await client.post("http://telegram-test:8081/control", json={"fail_send": 1})
    body = update(photo=True, caption="Ответ после commit")
    assert (await webhook(client, bots[0], body)).status_code == 503
    assert (
        await db.scalar(
            select(func.count()).select_from(Product).where(Product.update_id == body["update_id"])
        )
        == 1
    )
    assert (await webhook(client, bots[1], body)).status_code == 200
    db.expire_all()
    receipt = await db.get(BotUpdate, (123456, body["update_id"]))
    assert receipt and receipt.delivered
    assert (
        await db.scalar(
            select(func.count()).select_from(Product).where(Product.update_id == body["update_id"])
        )
        == 1
    )


async def test_upload_then_database_rollback_is_retryable(
    client: httpx.AsyncClient, db: AsyncSession, storage: Storage
) -> None:
    bots = replicas("bot", 8001)
    body = update(photo=True, caption="Откат транзакции")
    # A real PostgreSQL trigger fails after the real MinIO upload, before commit.
    async with db.begin():
        await db.execute(
            text(
                f"CREATE FUNCTION test_reject_{body['update_id']}() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN "
                f"IF NEW.update_id = {body['update_id']} THEN "
                "RAISE EXCEPTION 'test rollback'; END IF; RETURN NEW; END $$"
            )
        )
        await db.execute(
            text(
                f"CREATE TRIGGER test_reject_{body['update_id']} BEFORE INSERT ON products "
                f"FOR EACH ROW EXECUTE FUNCTION test_reject_{body['update_id']}()"
            )
        )
    try:
        assert (await webhook(client, bots[0], update(text="/create_product"))).status_code == 200
        assert (await webhook(client, bots[0], body)).status_code == 503
        assert (
            await db.scalar(select(Product).where(Product.update_id == body["update_id"])) is None
        )
        objects = await asyncio.to_thread(
            storage.client.list_objects_v2,
            Bucket=storage.bucket,
            Prefix=f"products/123456/{body['update_id']}/",
        )
        assert len(objects.get("Contents", [])) == 1
        await db.rollback()
    finally:
        async with db.begin():
            await db.execute(text(f"DROP TRIGGER test_reject_{body['update_id']} ON products"))
            await db.execute(text(f"DROP FUNCTION test_reject_{body['update_id']}()"))
    assert (await webhook(client, bots[1], body)).status_code == 200
    product = await db.scalar(select(Product).where(Product.update_id == body["update_id"]))
    assert product and await storage.read(product.object_key)
