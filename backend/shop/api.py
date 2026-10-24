import hmac
import io
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shop.cart import change_item, checkout, locked_owner, order_data, snapshot
from shop.config import Settings
from shop.db import connect
from shop.http import configure_http
from shop.models import BrowserSession, Order, Owner, Product
from shop.security import InvalidInitData, token_hash, validate_init_data
from shop.storage import Storage

settings = Settings()
engine, sessions = connect(settings)
storage = Storage(settings)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()
    await storage.close()


app = FastAPI(title="Каталог", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
configure_http(app)


async def database() -> AsyncIterator[AsyncSession]:
    async with sessions() as db, db.begin():
        yield db


DB = Annotated[AsyncSession, Depends(database, scope="function")]


async def current_session(request: Request, db: DB) -> BrowserSession:
    token = request.cookies.get(settings.session_cookie_name, "")
    session = await db.get(BrowserSession, token_hash(token)) if token else None
    if session is None or session.expires_at <= datetime.now(UTC):
        raise HTTPException(401, "Откройте каталог для создания сессии")
    expected_scope = request.headers.get("X-Checkout-Scope")
    if expected_scope is not None and expected_scope != str(session.owner_id):
        raise HTTPException(
            403,
            "Владелец сессии изменился; повторите авторизацию",
            headers={"X-Session-Error": "owner"},
        )
    return session


Session = Annotated[BrowserSession, Depends(current_session)]


async def csrf(
    request: Request, session: Session, x_csrf_token: Annotated[str, Header()] = ""
) -> None:
    if (
        request.headers.get("origin") != settings.public_origin
        or not x_csrf_token.isascii()
        or not hmac.compare_digest(x_csrf_token, session.csrf)
    ):
        raise HTTPException(403, "Проверка CSRF не пройдена", headers={"X-CSRF-Error": "1"})


Mutation = [Depends(csrf)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Version(StrictModel):
    version: int = Field(ge=0, le=2**53 - 1)


class Quantity(Version):
    quantity: int = Field(ge=1, le=99)


class TelegramLogin(StrictModel):
    init_data: str = Field(min_length=1, max_length=8192)


async def new_session(
    db: AsyncSession, response: Response, owner_id: uuid.UUID, *, telegram: bool = False
) -> BrowserSession:
    raw = secrets.token_urlsafe(32)
    lifetime = 86400 if telegram else 30 * 86400
    session = BrowserSession(
        token_hash=token_hash(raw),
        owner_id=owner_id,
        csrf=secrets.token_urlsafe(32),
        expires_at=datetime.now(UTC) + timedelta(seconds=lifetime),
    )
    db.add(session)
    await db.flush()
    response.set_cookie(
        settings.session_cookie_name,
        raw,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="none" if settings.cookie_secure else "lax",
        max_age=lifetime,
        path="/",
    )
    if settings.cookie_secure:
        # Python 3.13's cookie serializer lacks Partitioned; retain Starlette's other attributes.
        response.headers["set-cookie"] += "; Partitioned"
    return session


@app.get("/api/session")
async def bootstrap(request: Request, response: Response, db: DB) -> dict[str, str | bool]:
    token = request.cookies.get(settings.session_cookie_name, "")
    session = await db.get(BrowserSession, token_hash(token)) if token else None
    created = False
    if session is None or session.expires_at <= datetime.now(UTC):
        created = True
        owner = Owner()
        db.add(owner)
        await db.flush()
        session = await new_session(db, response, owner.id)
    existing_owner = await db.get(Owner, session.owner_id)
    return {
        "csrf_token": session.csrf,
        "kind": "telegram" if existing_owner and existing_owner.telegram_id else "guest",
        "checkout_scope": str(session.owner_id),
        "created": created,
    }


@app.post("/api/session/telegram", dependencies=Mutation)
async def telegram_login(
    body: TelegramLogin, response: Response, db: DB, session: Session
) -> dict[str, str]:
    try:
        user_id = validate_init_data(body.init_data, settings.bot_token.get_secret_value())
    except InvalidInitData as exc:
        raise HTTPException(401, str(exc)) from exc
    locked = await db.scalar(
        select(BrowserSession)
        .where(BrowserSession.token_hash == session.token_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None or locked.expires_at <= datetime.now(UTC):
        raise HTTPException(409, "Сессия обновлена другим запросом; повторите вход")
    session = locked
    await db.execute(
        insert(Owner)
        .values(id=uuid.uuid4(), telegram_id=user_id)
        .on_conflict_do_nothing(index_elements=[Owner.telegram_id])
    )
    owner = await db.scalar(select(Owner).where(Owner.telegram_id == user_id))
    assert owner is not None
    if session.owner_id == owner.id:
        return {
            "csrf_token": session.csrf,
            "kind": "telegram",
            "checkout_scope": str(owner.id),
        }
    await db.delete(session)
    fresh = await new_session(db, response, owner.id, telegram=True)
    return {"csrf_token": fresh.csrf, "kind": "telegram", "checkout_scope": str(owner.id)}


def product_data(product: Product) -> dict[str, Any]:
    return {
        "id": product.id,
        "name": product.name,
        "image_url": f"/api/products/{product.id}/image",
    }


@app.get("/api/products")
async def products(
    db: DB, before: Annotated[int | None, Query(gt=0, le=2**53 - 1)] = None
) -> dict[str, Any]:
    query = select(Product).order_by(Product.id.desc()).limit(21)
    if before is not None:
        query = query.where(Product.id < before)
    rows = list((await db.scalars(query)).all())
    return {
        "items": [product_data(p) for p in rows[:20]],
        "next_cursor": rows[19].id if len(rows) > 20 else None,
    }


async def find_product(db: AsyncSession, product_id: int) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "Товар не найден")
    return product


@app.get("/api/products/{product_id}")
async def product(product_id: Annotated[int, Path(gt=0, le=2**53 - 1)], db: DB) -> dict[str, Any]:
    return product_data(await find_product(db, product_id))


@app.get("/api/products/{product_id}/image")
async def image(product_id: Annotated[int, Path(gt=0, le=2**53 - 1)], db: DB) -> StreamingResponse:
    product = await find_product(db, product_id)
    try:
        data = await storage.read(product.object_key)
    except (BotoCoreError, ClientError, ValueError) as exc:
        raise HTTPException(503, "Изображение временно недоступно") from exc
    return StreamingResponse(
        io.BytesIO(data),
        media_type=product.content_type,
        headers={"Content-Length": str(len(data))},
    )


@app.get("/api/cart")
async def cart(db: DB, session: Session) -> dict[str, Any]:
    owner = await locked_owner(db, session.owner_id, read=True)
    return await snapshot(db, owner)


@app.put("/api/cart/items/{product_id}", dependencies=Mutation)
async def put_item(
    product_id: Annotated[int, Path(gt=0, le=2**53 - 1)], body: Quantity, db: DB, session: Session
) -> dict[str, Any]:
    return await change_item(db, session.owner_id, product_id, body.quantity, body.version)


@app.delete("/api/cart/items/{product_id}", dependencies=Mutation)
async def remove_item(
    product_id: Annotated[int, Path(gt=0, le=2**53 - 1)], body: Version, db: DB, session: Session
) -> dict[str, Any]:
    return await change_item(db, session.owner_id, product_id, None, body.version)


@app.post("/api/orders", dependencies=Mutation)
async def place_order(
    body: Version, db: DB, session: Session, idempotency_key: Annotated[uuid.UUID, Header()]
) -> dict[str, Any]:
    return await checkout(db, session.owner_id, idempotency_key, body.version)


@app.get("/api/orders/{order_id}")
async def get_order(order_id: uuid.UUID, db: DB, session: Session) -> dict[str, Any]:
    order = await db.scalar(
        select(Order).where(Order.id == order_id, Order.owner_id == session.owner_id)
    )
    if order is None:
        raise HTTPException(404, "Заказ не найден")
    return order_data(order)


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready() -> Response:
    try:
        async with sessions() as db:
            await db.execute(text("SELECT 1 FROM alembic_version LIMIT 1"))
        await storage.ready()
        return JSONResponse({"status": "ready"})
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)
