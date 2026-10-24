import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from shop.models import CartItem, Order, Owner, Product


class CartError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message


async def locked_owner(db: AsyncSession, owner_id: uuid.UUID, *, read: bool = False) -> Owner:
    owner = await db.scalar(select(Owner).where(Owner.id == owner_id).with_for_update(read=read))
    if owner is None:
        raise CartError(401, "Сессия недействительна")
    return owner


def check_version(owner: Owner, expected: int) -> None:
    if owner.cart_version != expected:
        raise CartError(409, "Корзина изменилась. Обновите её и повторите действие.")


async def snapshot(db: AsyncSession, owner: Owner) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(CartItem, Product)
            .join(Product)
            .where(CartItem.owner_id == owner.id)
            .order_by(Product.id)
        )
    ).all()
    return {
        "version": owner.cart_version,
        "items": [
            {
                "product_id": p.id,
                "name": p.name,
                "quantity": item.quantity,
                "image_url": f"/api/products/{p.id}/image",
            }
            for item, p in rows
        ],
    }


async def change_item(
    db: AsyncSession, owner_id: uuid.UUID, product_id: int, quantity: int | None, version: int
) -> dict[str, Any]:
    owner = await locked_owner(db, owner_id)
    check_version(owner, version)
    if await db.get(Product, product_id) is None:
        raise CartError(404, "Товар не найден")
    item = await db.get(CartItem, (owner_id, product_id))
    if quantity is None:
        if item:
            await db.delete(item)
    elif item:
        item.quantity = quantity
    else:
        count = len(
            (
                await db.scalars(select(CartItem.product_id).where(CartItem.owner_id == owner_id))
            ).all()
        )
        if count >= 100:
            raise CartError(422, "В корзине может быть не больше 100 разных товаров")
        db.add(CartItem(owner_id=owner_id, product_id=product_id, quantity=quantity))
    owner.cart_version += 1
    await db.flush()
    return await snapshot(db, owner)


def order_data(order: Order) -> dict[str, Any]:
    return {"id": str(order.id), "created_at": order.created_at.isoformat(), "items": order.items}


async def checkout(
    db: AsyncSession, owner_id: uuid.UUID, key: uuid.UUID, version: int
) -> dict[str, Any]:
    owner = await locked_owner(db, owner_id)
    previous = await db.scalar(
        select(Order).where(Order.owner_id == owner_id, Order.idempotency_key == key)
    )
    if previous:
        if previous.cart_version != version:
            raise CartError(409, "Ключ оформления уже использован для другого состояния корзины")
        return order_data(previous)
    check_version(owner, version)
    cart = await snapshot(db, owner)
    if not cart["items"]:
        raise CartError(422, "Корзина пуста")
    items = [
        {"product_id": row["product_id"], "name": row["name"], "quantity": row["quantity"]}
        for row in cart["items"]
    ]
    order = Order(owner_id=owner_id, idempotency_key=key, cart_version=version, items=items)
    db.add(order)
    await db.execute(delete(CartItem).where(CartItem.owner_id == owner_id))
    owner.cart_version += 1
    await db.flush()
    return order_data(order)
