from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from shop.config import Settings


def connect(settings: Settings) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=3,
        max_overflow=0,
        pool_timeout=3,
        pool_pre_ping=True,
        connect_args={
            "timeout": 3,
            "command_timeout": 12,
            "server_settings": {
                "lock_timeout": "5000",
                "statement_timeout": "10000",
                "idle_in_transaction_session_timeout": "60000",
            },
        },
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False)
