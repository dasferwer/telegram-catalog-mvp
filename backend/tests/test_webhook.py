from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from shop import webhook


@pytest.fixture
def registration(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://catalog.example")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.setenv("WEBHOOK_SECRET", "test-registration-secret")
    bot = AsyncMock()
    bot.get_webhook_info.return_value = SimpleNamespace(url="")
    monkeypatch.setattr(webhook, "create_bot", lambda settings: bot)
    return bot


async def test_registration_receives_messages_and_admin_button_callbacks(
    registration: AsyncMock,
) -> None:
    await webhook.main(False)
    options = registration.set_webhook.call_args.kwargs
    assert set(options["allowed_updates"]) == {"message", "callback_query"}
    assert registration.set_webhook.call_args.args == ("https://catalog.example/telegram/webhook",)
    assert options["drop_pending_updates"] is False
    assert options["secret_token"] == "test-registration-secret"
    registration.session.close.assert_awaited_once()


async def test_existing_webhook_requires_explicit_replacement(registration: AsyncMock) -> None:
    registration.get_webhook_info.return_value = SimpleNamespace(url="https://existing.example")
    with pytest.raises(SystemExit, match="existing webhook"):
        await webhook.main(False)
    registration.set_webhook.assert_not_awaited()
    registration.session.close.assert_awaited_once()


async def test_explicit_replacement_preserves_pending_updates(registration: AsyncMock) -> None:
    registration.get_webhook_info.return_value = SimpleNamespace(url="https://existing.example")
    await webhook.main(True)
    assert registration.set_webhook.call_args.kwargs["drop_pending_updates"] is False
