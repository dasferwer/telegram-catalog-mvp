from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from shop.config import Settings


def create_bot(settings: Settings) -> Bot:
    if settings.telegram_api_url:
        session = AiohttpSession(
            timeout=10, limit=4, api=TelegramAPIServer.from_base(settings.telegram_api_url)
        )
    else:
        session = AiohttpSession(timeout=10, limit=4)
    return Bot(token=settings.bot_token.get_secret_value(), session=session)
