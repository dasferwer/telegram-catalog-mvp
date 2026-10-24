import asyncio

import httpx
from conftest import replicas, update_id
from sqlalchemy.ext.asyncio import AsyncSession

from shop.models import Product
from shop.storage import Storage


async def test_catalog_photo_pagination_and_404(
    client: httpx.AsyncClient, db: AsyncSession, storage: Storage
) -> None:
    photo = (await client.get("http://telegram-test:8081/file/bottest/photo.jpg")).content
    batch = update_id()
    keys = [f"products/fixtures/{batch}/{i}" for i in range(23)]
    await asyncio.gather(*(storage.put(key, photo, "image/jpeg") for key in keys))
    for i, key in enumerate(keys):
        db.add(
            Product(
                name=f"Товар {i}",
                object_key=key,
                content_type="image/jpeg",
                size=len(photo),
                bot_id=999,
                update_id=update_id(),
            )
        )
    await db.commit()
    apis = replicas("api", 8000)
    response = await client.get(apis[0] + "/api/products")
    assert response.status_code == 200
    page = response.json()
    assert len(page["items"]) == 20
    ids = [p["id"] for p in page["items"]]
    assert ids == sorted(ids, reverse=True)
    next_page = (await client.get(apis[1] + f"/api/products?before={page['next_cursor']}")).json()
    assert not set(ids) & {p["id"] for p in next_page["items"]}
    assert (await client.get(apis[0] + "/api/products?before=1")).json()["items"] == []
    product = page["items"][0]
    assert (await client.get(apis[1] + f"/api/products/{product['id']}")).json() == product
    image = await client.get(apis[1] + product["image_url"])
    assert image.content == photo and image.headers["content-type"] == "image/jpeg"
    assert (await client.get(apis[0] + "/api/products/9007199254740991")).status_code == 404
    assert (await client.get(apis[0] + "/api/products/99999999999999999999")).status_code == 422
    assert (await client.get(apis[0] + "/api/products/1/image")).status_code in {200, 404}


async def test_body_size_is_bounded_even_with_chunked_request(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    async def chunks():
        for _ in range(5):
            yield b"x" * 20000

    response = await client.post(replicas("bot", 8001)[0] + "/telegram/webhook", content=chunks())
    assert response.status_code == 413
