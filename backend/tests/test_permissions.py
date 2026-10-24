import asyncio
import os
import uuid

import pytest
from botocore.exceptions import ClientError
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from shop.config import Settings
from shop.db import connect
from shop.storage import Storage


async def test_runtime_database_role_cannot_create_tables() -> None:
    settings = Settings()
    url = make_url(settings.database_url.get_secret_value()).set(
        username="catalog_app", password=os.environ["APP_DATABASE_PASSWORD"]
    )
    settings.database_url = SecretStr(url.render_as_string(hide_password=False))
    engine, sessions = connect(settings)
    name = "permission_probe_" + uuid.uuid4().hex
    try:
        async with sessions() as db:
            flags = (
                await db.execute(
                    text(
                        "SELECT rolsuper,rolcreaterole,rolcreatedb,rolbypassrls "
                        "FROM pg_roles WHERE rolname=current_user"
                    )
                )
            ).one()
            assert flags == (False, False, False, False)
            with pytest.raises(SQLAlchemyError):
                await db.execute(text(f"CREATE TABLE {name} (id int)"))
            await db.rollback()
    finally:
        await engine.dispose()


async def test_runtime_storage_policy_and_cancelled_real_uploads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    settings = Settings()
    settings.s3_access_key = SecretStr(os.environ["APP_S3_ACCESS_KEY"])
    settings.s3_secret_key = SecretStr(os.environ["APP_S3_SECRET_KEY"])
    storage = Storage(settings)
    release = threading.Event()
    entered = asyncio.Event()
    loop = asyncio.get_running_loop()
    original = storage.client.put_object
    key = "products/permission-probe/" + uuid.uuid4().hex

    def upload(**kwargs: object) -> object:
        loop.call_soon_threadsafe(entered.set)
        release.wait(3)
        return original(**kwargs)

    try:
        buckets = await asyncio.to_thread(storage.client.list_buckets)
        assert {bucket["Name"] for bucket in buckets["Buckets"]} == {storage.bucket}
        with pytest.raises(ClientError) as denied:
            await asyncio.to_thread(storage.client.get_bucket_policy, Bucket=storage.bucket)
        assert denied.value.response["Error"]["Code"] == "AccessDenied"
        with pytest.raises(ClientError):
            await asyncio.to_thread(
                storage.client.create_bucket, Bucket="forbidden-" + uuid.uuid4().hex
            )
        with pytest.raises(ClientError):
            await asyncio.to_thread(storage.client.delete_object, Bucket=storage.bucket, Key=key)
        with pytest.raises(ClientError):
            await storage.put("outside-products/" + uuid.uuid4().hex, b"probe", "image/png")
        monkeypatch.setattr(storage.client, "put_object", upload)
        task = asyncio.create_task(storage.put(key, b"probe", "image/png"))
        async with asyncio.timeout(2):
            await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        closing = asyncio.create_task(storage.close())
        await asyncio.sleep(0.05)
        assert not closing.done()
        release.set()
        await closing
        verification = Storage(settings)
        try:
            assert await verification.read(key) == b"probe"
        finally:
            await verification.close()
    finally:
        release.set()
        await storage.close()
