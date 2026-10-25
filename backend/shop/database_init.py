"""Права роли приложения на существующие таблицы без доступа к DDL."""

import asyncio
import os
import re

from sqlalchemy import text

from shop.config import Settings
from shop.db import connect


async def main() -> None:
    password = os.environ["APP_DATABASE_PASSWORD"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", password):
        raise ValueError("APP_DATABASE_PASSWORD must be a generated URL-safe secret")
    engine, sessions = connect(Settings())
    try:
        async with sessions() as connection, connection.begin():
            await connection.execute(text("SELECT pg_advisory_xact_lock(65427913)"))
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_roles WHERE rolname='catalog_app'")
            )
            if not exists:
                await connection.execute(text("CREATE ROLE catalog_app LOGIN"))
            # Допустимый алфавит пароля исключает SQL-разделители.
            await connection.execute(
                text(
                    "ALTER ROLE catalog_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    f"NOREPLICATION NOBYPASSRLS PASSWORD '{password}'"
                )
            )
            await connection.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
            await connection.execute(text("GRANT CONNECT ON DATABASE catalog TO catalog_app"))
            await connection.execute(text("GRANT USAGE ON SCHEMA public TO catalog_app"))
            await connection.execute(
                text(
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                    "IN SCHEMA public TO catalog_app"
                )
            )
            await connection.execute(
                text("REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM catalog_app")
            )
            await connection.execute(
                text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO catalog_app")
            )
            await connection.execute(
                text(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO catalog_app"
                )
            )
            await connection.execute(
                text(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    "GRANT USAGE, SELECT ON SEQUENCES TO catalog_app"
                )
            )
        print("Runtime database role is ready")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        raise SystemExit(f"Database initialization failed: {type(exc).__name__}") from None
