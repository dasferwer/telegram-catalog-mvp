import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from shop.config import Settings
from shop.models import Base


def run_migrations(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def main():
    engine = create_async_engine(Settings().database_url.get_secret_value())
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


asyncio.run(main())
