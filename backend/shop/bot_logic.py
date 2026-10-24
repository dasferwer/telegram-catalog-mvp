import asyncio
import hashlib
import io
from typing import Any

from aiogram import Bot, F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shop.config import Settings
from shop.models import AdminState, Product
from shop.storage import LimitedBuffer, Storage

router = Router()
Image.MAX_IMAGE_PIXELS = 16_000_000


def keyboard(settings: Settings, admin: bool) -> dict[str, Any]:
    buttons = [
        [
            InlineKeyboardButton(
                text="Открыть каталог", web_app=WebAppInfo(url=settings.public_origin)
            )
        ]
    ]
    if admin:
        buttons.append([InlineKeyboardButton(text="Создать товар", callback_data="create_product")])
    return InlineKeyboardMarkup(inline_keyboard=buttons).model_dump(mode="json", exclude_none=True)


def image_type(data: bytes) -> str:
    try:
        with Image.open(io.BytesIO(data), formats=("JPEG", "PNG")) as image:
            if image.width * image.height > 16_000_000 or image.format not in {"JPEG", "PNG"}:
                raise ValueError("Допустима фотография JPEG/PNG до 16 мегапикселей")
            kind = "image/jpeg" if image.format == "JPEG" else "image/png"
            image.load()
            return kind
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Не удалось прочитать фотографию JPEG/PNG") from exc


async def message_handler(
    message: Message,
    bot: Bot,
    db: AsyncSession,
    settings: Settings,
    storage: Storage,
    update_id: int,
) -> dict[str, Any] | None:
    if message.chat.type != "private" or message.from_user is None:
        return None
    user_id = message.from_user.id
    admin = user_id in settings.admins
    command = (message.text or "").split(" ", 1)[0].split("@", 1)[0]

    def reply(text: str, *, with_keyboard: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {"chat_id": message.chat.id, "text": text}
        if with_keyboard:
            result["reply_markup"] = keyboard(settings, admin)
        return result

    create = command == "/create_product" or message.text == "Создать товар"
    if not admin:
        return reply("Доступ запрещён" if create else "У меня есть товар")
    await db.execute(
        insert(AdminState)
        .values(bot_id=bot.id, user_id=user_id, waiting=False)
        .on_conflict_do_nothing()
    )
    state = await db.scalar(
        select(AdminState)
        .where(AdminState.bot_id == bot.id, AdminState.user_id == user_id)
        .with_for_update()
    )
    assert state is not None
    if command == "/start":
        state.waiting = False
        return reply("У меня есть товар")
    if create:
        state.waiting = True
        return reply(
            "Отправьте фотографию и название в подписи одним сообщением "
            "(до 200 символов, JPEG/PNG до 5 МиБ).",
            with_keyboard=False,
        )
    if not state.waiting:
        return reply("У меня есть товар")
    if message.media_group_id:
        return reply(
            "Альбомы не поддерживаются. Отправьте одну фотографию с названием в подписи.",
            with_keyboard=False,
        )
    name = (message.caption or "").strip()
    if not message.photo or not 1 <= len(name) <= 200:
        return reply(
            "Нужны фотография и название в её подписи одним сообщением; "
            "название — от 1 до 200 символов.",
            with_keyboard=False,
        )
    photo = message.photo[-1]
    if photo.file_size is not None and photo.file_size > settings.max_photo_bytes:
        return reply(
            "Фотография слишком большая. Отправьте JPEG/PNG до 5 МиБ.", with_keyboard=False
        )
    try:
        with LimitedBuffer(settings.max_photo_bytes) as buffer:
            await bot.download(photo.file_id, destination=buffer, timeout=10)
            data = buffer.getvalue()
        kind = await asyncio.to_thread(image_type, data)
    except ValueError as exc:
        return reply(str(exc), with_keyboard=False)
    digest = hashlib.sha256(data).hexdigest()
    key = f"products/{bot.id}/{update_id}/{digest}"
    await storage.put(key, data, kind)
    product = Product(
        name=name,
        object_key=key,
        content_type=kind,
        size=len(data),
        bot_id=bot.id,
        update_id=update_id,
    )
    db.add(product)
    state.waiting = False
    await db.flush()
    return reply(f"Товар создан: {product.name} (№{product.id})")


router.message()(message_handler)


@router.callback_query(F.data == "create_product")
async def create_callback(
    callback: CallbackQuery,
    bot: Bot,
    db: AsyncSession,
    settings: Settings,
    storage: Storage,
    update_id: int,
) -> dict[str, Any] | None:
    if not isinstance(callback.message, Message):
        return None
    message = callback.message.model_copy(
        update={"from_user": callback.from_user, "text": "/create_product"}
    )
    return await message_handler(message, bot, db, settings, storage, update_id)
