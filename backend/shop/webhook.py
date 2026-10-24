import argparse
import asyncio

from shop.config import Settings
from shop.telegram import create_bot


async def main(replace_existing: bool) -> None:
    settings = Settings()
    if (
        not settings.public_origin.startswith("https://")
        or not settings.webhook_secret.get_secret_value()
    ):
        raise SystemExit("HTTPS PUBLIC_ORIGIN and WEBHOOK_SECRET are required")
    bot = create_bot(settings)
    try:
        info = await bot.get_webhook_info()
        target = settings.public_origin + "/telegram/webhook"
        if info.url and not replace_existing:
            raise SystemExit(
                "An existing webhook is configured. Inspect it with your administrator; "
                "rerun with --replace-existing only with permission."
            )
        await bot.set_webhook(
            target,
            secret_token=settings.webhook_secret.get_secret_value(),
            allowed_updates=["message", "callback_query"],
            max_connections=8,
            drop_pending_updates=False,
        )
        print("Webhook configured; pending updates preserved")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--replace-existing", action="store_true")
    asyncio.run(main(parser.parse_args().replace_existing))
