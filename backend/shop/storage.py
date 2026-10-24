import asyncio
import io
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

import boto3
from botocore.config import Config

from shop.config import Settings

T = TypeVar("T")


class Storage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self.limit = settings.max_photo_bytes
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            region_name="us-east-1",
            config=Config(
                connect_timeout=2,
                read_timeout=5,
                retries={"total_max_attempts": 2, "mode": "standard"},
                max_pool_connections=4,
            ),
        )
        self.slots = asyncio.Semaphore(4)
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="s3")
        self.pending: set[asyncio.Future[Any]] = set()
        self.closed = False

    async def _run(self, operation: Callable[[], T]) -> T:
        await self.slots.acquire()
        if self.closed:
            self.slots.release()
            raise RuntimeError("Storage is closed")
        future = asyncio.get_running_loop().run_in_executor(self.executor, operation)
        self.pending.add(future)

        def finished(done: asyncio.Future[T]) -> None:
            self.pending.discard(done)
            self.slots.release()
            if not done.cancelled():
                done.exception()

        future.add_done_callback(finished)
        return await asyncio.shield(future)

    async def ready(self) -> None:
        await self._run(lambda: self.client.head_bucket(Bucket=self.bucket))

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await self._run(
            lambda: self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        )

    async def read(self, key: str) -> bytes:
        def load() -> bytes:
            result = self.client.get_object(Bucket=self.bucket, Key=key)
            with result["Body"] as body:
                data: bytes = body.read(self.limit + 1)
            if len(data) > self.limit:
                raise ValueError("Stored image exceeds configured limit")
            return data

        return await self._run(load)

    async def close(self) -> None:
        self.closed = True
        if self.pending:
            await asyncio.shield(asyncio.gather(*self.pending, return_exceptions=True))
        await asyncio.to_thread(self.executor.shutdown, wait=True)
        self.client.close()


class LimitedBuffer(io.BytesIO):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit

    def write(self, data: Any) -> int:
        if self.tell() + len(data) > self.limit:
            raise ValueError("Фотография больше допустимого размера")
        return super().write(data)
