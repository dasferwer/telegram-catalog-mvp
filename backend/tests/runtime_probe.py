"""Fault scenarios coordinated with scripts/test-runtime.py; no Docker socket in applications."""

import asyncio
import json
import uuid

import httpx
from conftest import Browser, replicas, update, webhook
from sqlalchemy import select, text

from shop.config import Settings
from shop.db import connect
from shop.models import BotUpdate, Product
from shop.storage import Storage


async def action(action_name: str, instance: str) -> None:
    print("ACTION " + json.dumps({"action": action_name, "instance": instance}), flush=True)
    assert await asyncio.to_thread(input) == "ok"


async def eventually(check, deadline_seconds: float = 40):
    async with asyncio.timeout(deadline_seconds):
        while True:
            try:
                result = await check()
                if result:
                    return result
            except (httpx.HTTPError, OSError):
                pass
            await asyncio.sleep(0.5)


async def main() -> None:
    engine, sessions = connect(Settings())
    storage = Storage(Settings())
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            bots = replicas("bot", 8001)
            apis = replicas("api", 8000)
            webs = replicas("web", 3000)
            assert len(bots) == len(apis) == len(webs) == 2
            ids = {
                base: (
                    await client.get(base + ("/health" if base in webs else "/health/live"))
                ).headers.get("x-instance-id")
                for base in bots + apis
            }
            web_ids = {
                base: (await client.get(base + "/health")).json()["instance"] for base in webs
            }

            async def ready(base: str, path: str = "/health/ready") -> bool:
                return (await client.get(base + path)).status_code == 200

            async def verify_product(body):
                async with sessions() as db:
                    rows = (
                        await db.scalars(
                            select(Product).where(Product.update_id == body["update_id"])
                        )
                    ).all()
                    assert len(rows) == 1
                    data = await storage.read(rows[0].object_key)
                    assert data.startswith(b"\xff\xd8")
                    return rows[0]

            # Start on one replica, stop it, complete the persistent dialog on the other.
            assert (
                await webhook(client, bots[0], update(text="/create_product"))
            ).status_code == 200
            await action("stop", ids[bots[0]])
            body = update(photo=True, caption="После остановки реплики")
            assert (await webhook(client, bots[1], body)).status_code == 200
            product = await verify_product(body)

            async def webhook_survives():
                response = await webhook(client, "http://gateway:8080", body)
                return (
                    response.status_code == 200
                    and response.headers["x-instance-id"] == ids[bots[1]]
                )

            await eventually(webhook_survives)
            await action("start", ids[bots[0]])
            await eventually(lambda: ready(bots[0]))
            observed_bots = set()

            async def bot_pool_restored():
                response = await webhook(client, "http://gateway:8080", body)
                if response.status_code == 200:
                    observed_bots.add(response.headers["x-instance-id"])
                return len(observed_bots) == 2

            await eventually(bot_pool_restored)
            print(f"PASS persistent bot dialog; gateway sees {sorted(observed_bots)}", flush=True)

            # No success is acknowledged while storage is unavailable; the same update retries.
            assert (
                await webhook(client, bots[0], update(text="/create_product"))
            ).status_code == 200
            # Infrastructure hostnames are resolved by the host coordinator via service names below.
            await action("stop", "service:minio")
            body = update(photo=True, caption="Повтор после MinIO")
            assert (await webhook(client, bots[0], body)).status_code == 503
            async with sessions() as db:
                assert (
                    await db.scalar(select(Product).where(Product.update_id == body["update_id"]))
                    is None
                )
            await action("start", "service:minio")
            await eventually(lambda: ready(bots[0]))
            assert (await webhook(client, bots[1], body)).status_code == 200
            await verify_product(body)
            print("PASS MinIO outage and retry", flush=True)

            assert (
                await webhook(client, bots[0], update(text="/create_product"))
            ).status_code == 200
            await action("stop", "service:postgres")
            body = update(photo=True, caption="Повтор после PostgreSQL")
            assert (await webhook(client, bots[0], body)).status_code == 503
            error_page = await client.get("http://gateway:8080/")
            assert "Не удалось загрузить каталог" in error_page.text
            await action("start", "service:postgres")
            await eventually(lambda: ready(bots[1]))
            assert (await webhook(client, bots[1], body)).status_code == 200
            await verify_product(body)
            print("PASS PostgreSQL outage and retry", flush=True)

            # Pause insertion AFTER successful object upload using a real DB trigger.
            body = update(photo=True, caption="Остановка после загрузки")
            suffix = str(body["update_id"])
            async with sessions() as db, db.begin():
                await db.execute(
                    text(
                        f"CREATE FUNCTION test_sleep_{suffix}() RETURNS trigger "
                        "LANGUAGE plpgsql AS $$ BEGIN "
                        f"IF NEW.update_id = {suffix} THEN PERFORM pg_sleep(8); "
                        "END IF; RETURN NEW; END $$"
                    )
                )
                await db.execute(
                    text(
                        f"CREATE TRIGGER test_sleep_{suffix} BEFORE INSERT ON products "
                        f"FOR EACH ROW EXECUTE FUNCTION test_sleep_{suffix}()"
                    )
                )
            try:
                assert (
                    await webhook(client, bots[0], update(text="/create_product"))
                ).status_code == 200
                task = asyncio.create_task(webhook(client, bots[0], body))

                async def uploaded():
                    result = await asyncio.to_thread(
                        storage.client.list_objects_v2,
                        Bucket=storage.bucket,
                        Prefix=f"products/123456/{suffix}/",
                    )
                    return bool(result.get("Contents"))

                await eventually(uploaded)
                await action("kill", ids[bots[0]])
                outcome = await asyncio.gather(task, return_exceptions=True)
                assert isinstance(outcome[0], Exception) or outcome[0].status_code != 200
                async with sessions() as db:
                    assert (
                        await db.scalar(
                            select(Product).where(Product.update_id == body["update_id"])
                        )
                        is None
                    )
                    assert await db.get(BotUpdate, (123456, body["update_id"])) is None
            finally:

                async def rollback_finished():
                    async with sessions() as db:
                        return not await db.scalar(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                                "WHERE wait_event = 'PgSleep')"
                            )
                        )

                await eventually(rollback_finished)
                async with sessions() as db, db.begin():
                    await db.execute(text(f"DROP TRIGGER test_sleep_{suffix} ON products"))
                    await db.execute(text(f"DROP FUNCTION test_sleep_{suffix}()"))
                await action("start", ids[bots[0]])
            assert (await webhook(client, bots[1], body)).status_code == 200
            await verify_product(body)
            await eventually(lambda: ready(bots[0]))
            print(
                "PASS kill after object upload before DB commit; retry creates one product",
                flush=True,
            )

            # A committed product survives process death while confirmation is being sent.
            assert (
                await webhook(client, bots[0], update(text="/create_product"))
            ).status_code == 200
            await client.post("http://telegram-test:8081/control", json={"send_delay": 30})
            body = update(photo=True, caption="Остановка после commit")
            task = asyncio.create_task(webhook(client, bots[0], body))

            async def committed():
                async with sessions() as db:
                    return await db.scalar(
                        select(Product.id).where(Product.update_id == body["update_id"])
                    )

            await eventually(committed)
            await action("kill", ids[bots[0]])
            await asyncio.gather(task, return_exceptions=True)
            await client.post("http://telegram-test:8081/control", json={"send_delay": 0})
            assert (await webhook(client, bots[1], body)).status_code == 200
            await verify_product(body)
            await action("start", ids[bots[0]])
            await eventually(lambda: ready(bots[0]))
            print(
                "PASS kill after commit; confirmation retry without duplicate product", flush=True
            )

            # Prove gateway availability and persistent cart/order while each app replica stops.
            browser = await Browser(client, ["http://gateway:8080"] * 2).start()
            cart = (
                await browser.request(
                    "PUT", f"/api/cart/items/{product.id}", json={"quantity": 2, "version": 0}
                )
            ).json()
            for service, base, instance in [
                ("api", apis[0], ids[apis[0]]),
                ("web", webs[0], web_ids[webs[0]]),
            ]:
                await action("stop", instance)

                async def gateway_available():
                    response = await client.get("http://gateway:8080/health")
                    return response.status_code == 200

                await eventually(gateway_available)

                async def cart_available():
                    response = await browser.request("GET", "/api/cart")
                    return response.status_code == 200 and response.json() == cart

                await eventually(cart_available)

                async def catalog_available():
                    response = await client.get("http://gateway:8080/")
                    return response.status_code == 200 and product.name in response.text

                await eventually(catalog_available)
                await action("start", instance)
                await eventually(
                    lambda base=base, service=service: ready(
                        base, "/health" if service == "web" else "/health/ready"
                    )
                )
                observed = set()

                async def both_back(service=service, observed=observed):
                    response = (
                        await client.get("http://gateway:8080/health")
                        if service == "web"
                        else await browser.request("GET", "/api/cart")
                    )
                    if response.status_code == 200:
                        observed.add(
                            response.json()["instance"]
                            if service == "web"
                            else response.headers["x-instance-id"]
                        )
                    return len(observed) == 2

                await eventually(both_back)
                print(
                    f"PASS {service} replica stop/return; gateway sees {sorted(observed)}",
                    flush=True,
                )
            order = await browser.request(
                "POST",
                "/api/orders",
                json={"version": cart["version"]},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
            assert order.status_code == 200
            assert order.json()["items"][0]["quantity"] == 2
            print("PASS all runtime fault scenarios; all replicas restored", flush=True)
    finally:
        async with httpx.AsyncClient() as cleanup:
            await cleanup.post(
                "http://telegram-test:8081/control",
                json={"send_delay": 0, "file_delay": 0, "fail_send": 0},
            )
        await storage.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
