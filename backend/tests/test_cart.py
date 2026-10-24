import asyncio
import time
import uuid

import httpx
import pytest
from conftest import Browser, replicas
from sqlalchemy.ext.asyncio import AsyncSession
from test_security import signed

from shop.models import Product


async def test_bootstrap_distinguishes_new_and_existing_guests(client: httpx.AsyncClient) -> None:
    apis = replicas("api", 8000)
    first = await client.get(apis[0] + "/api/session", headers={"Cookie": ""})
    assert first.status_code == 200
    assert first.json()["created"] is True
    cookie = first.headers["set-cookie"].split(";", 1)[0]
    reused = await client.get(apis[1] + "/api/session", headers={"Cookie": cookie})
    assert reused.status_code == 200
    assert reused.json()["created"] is False
    assert reused.json()["checkout_scope"] == first.json()["checkout_scope"]
    assert "set-cookie" not in reused.headers


async def test_session_cart_order_isolation_and_idempotency(
    client: httpx.AsyncClient, product: Product
) -> None:
    apis = replicas("api", 8000)
    a = await Browser(client, apis).start()
    b = await Browser(client, apis).start()
    assert a.headers["Cookie"] != b.headers["Cookie"]
    cart = (await a.request("GET", "/api/cart", replica=1)).json()
    assert cart == {"version": 0, "items": []}
    response = await a.request(
        "PUT", f"/api/cart/items/{product.id}", json={"quantity": 2, "version": 0}
    )
    assert response.status_code == 200
    cart = response.json()
    other_replica = await a.request("GET", "/api/cart", replica=1)
    assert other_replica.json() == cart
    assert response.headers["x-instance-id"] != other_replica.headers["x-instance-id"]
    assert (await b.request("GET", "/api/cart")).json()["items"] == []
    assert (
        await a.request("PUT", f"/api/cart/items/{product.id}", json={"quantity": 3, "version": 0})
    ).status_code == 409
    key = str(uuid.uuid4())
    requests = [
        a.request(
            "POST",
            "/api/orders",
            replica=i % 2,
            json={"version": cart["version"]},
            headers={"Idempotency-Key": key},
        )
        for i in range(6)
    ]
    responses = await asyncio.gather(*requests)
    assert {r.status_code for r in responses} == {200}
    assert len({r.json()["id"] for r in responses}) == 1
    order = responses[0].json()
    assert order["items"] == [{"product_id": product.id, "name": product.name, "quantity": 2}]
    assert (await a.request("GET", "/api/cart", replica=1)).json()["items"] == []
    assert (await b.request("GET", "/api/orders/" + order["id"])).status_code == 404
    assert (await a.request("GET", "/api/orders/" + order["id"], replica=1)).json() == order
    assert (
        await a.request(
            "POST",
            "/api/orders",
            json={"version": cart["version"] + 1},
            headers={"Idempotency-Key": key},
        )
    ).status_code == 409
    assert (
        await a.request(
            "POST",
            "/api/orders",
            json={"version": cart["version"] + 1},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
    ).status_code == 422
    print(
        "API replicas:", response.headers["x-instance-id"], other_replica.headers["x-instance-id"]
    )


@pytest.mark.parametrize("quantity", [0, -1, 100, 1.5, "2", True, None])
async def test_quantity_validation(
    client: httpx.AsyncClient, product: Product, quantity: object
) -> None:
    browser = await Browser(client, replicas("api", 8000)).start()
    response = await browser.request(
        "PUT", f"/api/cart/items/{product.id}", json={"quantity": quantity, "version": 0}
    )
    assert response.status_code == 422
    assert (await browser.request("GET", "/api/cart")).json()["version"] == 0


async def test_csrf_missing_product_and_update_delete(
    client: httpx.AsyncClient, product: Product
) -> None:
    browser = await Browser(client, replicas("api", 8000)).start()
    path = f"/api/cart/items/{product.id}"
    for headers in [{"Origin": "https://attacker.invalid"}, {"X-CSRF-Token": "wrong"}]:
        assert (
            await browser.request("PUT", path, json={"quantity": 1, "version": 0}, headers=headers)
        ).status_code == 403
    assert (
        await browser.request(
            "PUT", "/api/cart/items/999999999999", json={"quantity": 1, "version": 0}
        )
    ).status_code == 404
    cart = (await browser.request("PUT", path, json={"quantity": 1, "version": 0})).json()
    cart = (
        await browser.request("PUT", path, json={"quantity": 3, "version": cart["version"]})
    ).json()
    assert cart["items"][0]["quantity"] == 3
    cart = (await browser.request("DELETE", path, json={"version": cart["version"]})).json()
    assert not cart["items"]
    assert (
        await browser.request(
            "PUT",
            path,
            json={"quantity": 1, "version": cart["version"], "owner_id": str(uuid.uuid4())},
        )
    ).status_code == 422


async def test_checkout_vs_mutation_has_explicit_conflict(
    client: httpx.AsyncClient, product: Product
) -> None:
    browser = await Browser(client, replicas("api", 8000)).start()
    path = f"/api/cart/items/{product.id}"
    cart = (await browser.request("PUT", path, json={"quantity": 1, "version": 0})).json()
    checkout, mutation = await asyncio.gather(
        browser.request(
            "POST",
            "/api/orders",
            json={"version": cart["version"]},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        ),
        browser.request("PUT", path, replica=1, json={"quantity": 4, "version": cart["version"]}),
    )
    assert sorted([checkout.status_code, mutation.status_code]) == [200, 409]
    current = (await browser.request("GET", "/api/cart")).json()
    if mutation.status_code == 200:
        assert current["items"][0]["quantity"] == 4
    else:
        assert current["items"] == []
        assert checkout.json()["items"][0]["quantity"] == 1


async def test_telegram_identity_validation_and_shared_owner(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    apis = replicas("api", 8000)
    a = await Browser(client, apis).start()
    b = await Browser(client, apis).start()
    for invalid in ["bad", signed(int(time.time()) - 3601), signed().replace("Test", "Fake")]:
        assert (
            await a.request("POST", "/api/session/telegram", json={"init_data": invalid})
        ).status_code == 401
    for browser in [a, b]:
        result = await browser.request(
            "POST",
            "/api/session/telegram",
            json={"init_data": signed(int(time.time()), user_id=1234)},
        )
        assert result.status_code == 200, result.text
        browser.headers["Cookie"] = result.headers["set-cookie"].split(";", 1)[0]
        browser.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    assert (await a.request("GET", "/api/cart")).json() == (
        await b.request("GET", "/api/cart", replica=1)
    ).json()


async def test_order_keeps_product_name_snapshot(
    client: httpx.AsyncClient, product: Product, db: AsyncSession
) -> None:
    browser = await Browser(client, replicas("api", 8000)).start()
    cart = (
        await browser.request(
            "PUT", f"/api/cart/items/{product.id}", json={"quantity": 2, "version": 0}
        )
    ).json()
    order = (
        await browser.request(
            "POST",
            "/api/orders",
            json={"version": cart["version"]},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
    ).json()
    original_name = product.name
    product.name = "Переименован после заказа"
    await db.commit()
    saved = (await browser.request("GET", "/api/orders/" + order["id"])).json()
    assert saved["items"][0]["name"] == original_name


async def test_commit_failure_does_not_return_success_or_clear_cart(
    client: httpx.AsyncClient, product: Product, db: AsyncSession
) -> None:
    from sqlalchemy import text

    browser = await Browser(client, replicas("api", 8000)).start()
    cart = (
        await browser.request(
            "PUT", f"/api/cart/items/{product.id}", json={"quantity": 2, "version": 0}
        )
    ).json()
    key = str(uuid.uuid4())
    suffix = key.replace("-", "")
    await db.rollback()
    async with db.begin():
        await db.execute(
            text(
                f"CREATE FUNCTION test_commit_{suffix}() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN "
                f"IF NEW.idempotency_key = '{key}'::uuid THEN RAISE EXCEPTION 'test commit'; "
                "END IF; RETURN NEW; END $$"
            )
        )
        await db.execute(
            text(
                f"CREATE CONSTRAINT TRIGGER test_commit_{suffix} AFTER INSERT ON orders "
                "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
                f"EXECUTE FUNCTION test_commit_{suffix}()"
            )
        )
    try:
        response = await browser.request(
            "POST",
            "/api/orders",
            json={"version": cart["version"]},
            headers={"Idempotency-Key": key},
        )
        assert response.status_code == 503
        assert (await browser.request("GET", "/api/cart", replica=1)).json() == cart
    finally:
        async with db.begin():
            await db.execute(text(f"DROP TRIGGER test_commit_{suffix} ON orders"))
            await db.execute(text(f"DROP FUNCTION test_commit_{suffix}()"))
    response = await browser.request(
        "POST",
        "/api/orders",
        replica=1,
        json={"version": cart["version"]},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 200


async def test_non_ascii_csrf_is_rejected_without_server_error(client: httpx.AsyncClient) -> None:
    browser = await Browser(client, replicas("api", 8000)).start()
    headers = {key.encode(): value.encode() for key, value in browser.headers.items()}
    headers[b"X-CSRF-Token"] = b"\xe9"
    for base in browser.apis:
        response = await client.put(
            base + "/api/cart/items/1", headers=headers, json={"quantity": 1, "version": 0}
        )
        assert response.status_code == 403


async def test_repeated_telegram_login_preserves_other_tabs(
    client: httpx.AsyncClient, product: Product
) -> None:
    browser = await Browser(client, replicas("api", 8000)).start()
    data = {"init_data": signed(int(time.time()), user_id=time.time_ns() % 10**12)}
    first = await browser.request("POST", "/api/session/telegram", json=data)
    assert first.status_code == 200
    browser.headers["Cookie"] = first.headers["set-cookie"].split(";", 1)[0]
    browser.headers["X-CSRF-Token"] = first.json()["csrf_token"]
    replies = await asyncio.gather(
        *(
            browser.request("POST", "/api/session/telegram", replica=i % 2, json=data)
            for i in range(4)
        )
    )
    assert {r.status_code for r in replies} == {200}
    assert all("set-cookie" not in r.headers for r in replies)
    assert all(r.json() == first.json() for r in replies)
    cart = (await browser.request("GET", "/api/cart")).json()
    assert (
        await browser.request(
            "PUT",
            f"/api/cart/items/{product.id}",
            json={"quantity": 2, "version": cart["version"]},
            replica=1,
        )
    ).status_code == 200
    assert (
        await browser.request("POST", "/api/session/telegram", json={"init_data": "hash=bad"})
    ).status_code == 401


async def test_concurrent_first_login_rotates_cookie_only_once(client: httpx.AsyncClient) -> None:
    browser = await Browser(client, replicas("api", 8000)).start()
    data = {"init_data": signed(int(time.time()), user_id=time.time_ns() % 10**12)}
    replies = await asyncio.gather(
        *(
            browser.request("POST", "/api/session/telegram", replica=i % 2, json=data)
            for i in range(4)
        )
    )
    winners = [r for r in replies if r.status_code == 200]
    assert len(winners) == 1
    assert all(r.status_code in {200, 401, 409} for r in replies)
    assert sum("set-cookie" in r.headers for r in replies) == 1
    first = winners[0]
    browser.headers["Cookie"] = first.headers["set-cookie"].split(";", 1)[0]
    browser.headers["X-CSRF-Token"] = first.json()["csrf_token"]
    assert (
        await browser.request("POST", "/api/session/telegram", json=data)
    ).json() == first.json()


async def test_checkout_scope_survives_distinct_telegram_sessions(
    client: httpx.AsyncClient,
) -> None:
    browsers = [await Browser(client, replicas("api", 8000)).start() for _ in range(2)]
    data = {"init_data": signed(int(time.time()), user_id=time.time_ns() % 10**12)}
    guests = [(await b.request("GET", "/api/session")).json() for b in browsers]
    assert guests[0]["checkout_scope"] != guests[1]["checkout_scope"]
    replies = await asyncio.gather(
        *(
            b.request("POST", "/api/session/telegram", replica=i, json=data)
            for i, b in enumerate(browsers)
        )
    )
    assert all(r.status_code == 200 for r in replies)
    assert replies[0].json()["csrf_token"] != replies[1].json()["csrf_token"]
    assert replies[0].json()["checkout_scope"] == replies[1].json()["checkout_scope"]


async def test_expected_owner_never_authorizes_another_session(
    client: httpx.AsyncClient, product: Product
) -> None:
    a = await Browser(client, replicas("api", 8000)).start()
    b = await Browser(client, replicas("api", 8000)).start()
    own_scope = (await a.request("GET", "/api/session")).json()["checkout_scope"]
    other_scope = (await b.request("GET", "/api/session")).json()["checkout_scope"]
    for replica in range(2):
        response = await a.request(
            "GET", "/api/cart", replica=replica, headers={"X-Checkout-Scope": other_scope}
        )
        assert response.status_code == 403
        assert response.headers["X-Session-Error"] == "owner"
        assert "items" not in response.json()
        response = await a.request(
            "PUT",
            f"/api/cart/items/{product.id}",
            replica=replica,
            headers={"X-Checkout-Scope": other_scope},
            json={"quantity": 1, "version": 0},
        )
        assert response.status_code == 403
    result = await a.request("GET", "/api/cart", headers={"X-Checkout-Scope": own_scope})
    assert result.json() == {"version": 0, "items": []}
    assert (await b.request("GET", "/api/cart")).json() == result.json()
