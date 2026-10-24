import asyncio
import hmac
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aiogram import Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from shop.bot_logic import router
from shop.config import Settings
from shop.db import connect
from shop.http import configure_http
from shop.models import BotUpdate
from shop.storage import Storage
from shop.telegram import create_bot

settings = Settings()
if not settings.webhook_secret.get_secret_value():
    raise RuntimeError("WEBHOOK_SECRET is required")
engine, sessions = connect(settings)
storage = Storage(settings)
bot = create_bot(settings)
dispatcher = Dispatcher(disable_fsm=True)
dispatcher.include_router(router)
slots = asyncio.Semaphore(4)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await bot.session.close()
    await dispatcher.storage.close()
    await engine.dispose()
    await storage.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
configure_http(app)


async def process(update: Update) -> None:
    async with sessions() as db, db.begin():
        inserted = await db.scalar(
            insert(BotUpdate)
            .values(bot_id=bot.id, update_id=update.update_id)
            .on_conflict_do_nothing()
            .returning(BotUpdate.update_id)
        )
        if inserted is not None:
            result = await dispatcher.feed_update(
                bot, update, db=db, storage=storage, settings=settings, update_id=update.update_id
            )
            receipt = await db.get(BotUpdate, (bot.id, update.update_id))
            assert receipt is not None
            receipt.reply = result if isinstance(result, dict) else None
            receipt.delivered = receipt.reply is None
    # Product and state are committed before the separate, retryable external reply.
    async with sessions() as db, db.begin():
        receipt = await db.scalar(
            select(BotUpdate)
            .where(BotUpdate.bot_id == bot.id, BotUpdate.update_id == update.update_id)
            .with_for_update()
        )
        assert receipt is not None
        if not receipt.delivered and receipt.reply:
            await bot(SendMessage.model_validate(receipt.reply))
            if update.callback_query:
                try:
                    await bot.answer_callback_query(update.callback_query.id)
                except TelegramBadRequest:
                    # Expired callback acknowledgements are cosmetic; the durable reply was sent.
                    pass
            receipt.delivered = True


@app.post("/telegram/webhook")
async def webhook(request: Request) -> JSONResponse:
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(
        supplied.encode(), settings.webhook_secret.get_secret_value().encode()
    ):
        raise HTTPException(403, "Неверный секрет webhook")
    try:
        update = Update.model_validate(await request.json(), context={"bot": bot})
        if not 0 <= update.update_id < 2**63:
            raise ValueError("update_id outside supported range")
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, "Некорректное обновление") from exc
    try:
        await asyncio.wait_for(slots.acquire(), timeout=0.5)
    except TimeoutError as exc:
        raise HTTPException(503, "Обработчики заняты; повторите запрос") from exc
    try:
        async with asyncio.timeout(40):
            await process(update)
    except Exception as exc:
        # Never log request bodies, bot tokens, S3 credentials or SDK exception URLs.
        print(
            f"webhook_retry instance={socket.gethostname()} "
            f"update={update.update_id} type={type(exc).__name__}",
            flush=True,
        )
        return JSONResponse({"detail": "Временный сбой; повторите обновление"}, status_code=503)
    finally:
        slots.release()
    return JSONResponse({"ok": True})


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready() -> JSONResponse:
    try:
        async with sessions() as db:
            await db.execute(text("SELECT 1 FROM alembic_version LIMIT 1"))
        await storage.ready()
        return JSONResponse({"status": "ready"})
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)
