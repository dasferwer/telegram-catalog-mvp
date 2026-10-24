import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Owner(Base):
    __tablename__ = "owners"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    cart_version: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    __table_args__ = (CheckConstraint("cart_version >= 0"),)


class BrowserSession(Base):
    __tablename__ = "browser_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("owners.id"), index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    object_key: Mapped[str] = mapped_column(String(200), unique=True)
    content_type: Mapped[str] = mapped_column(String(40))
    size: Mapped[int] = mapped_column(Integer)
    bot_id: Mapped[int] = mapped_column(BigInteger)
    update_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("bot_id", "update_id"),
        CheckConstraint("length(name) BETWEEN 1 AND 200"),
        CheckConstraint("size > 0"),
    )


class CartItem(Base):
    __tablename__ = "cart_items"
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("owners.id"), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)
    __table_args__ = (CheckConstraint("quantity BETWEEN 1 AND 99"),)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("owners.id"), index=True)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID)
    cart_version: Mapped[int] = mapped_column(BigInteger)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key"),
        CheckConstraint("jsonb_array_length(items) > 0"),
    )


class AdminState(Base):
    __tablename__ = "admin_states"
    bot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    waiting: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class BotUpdate(Base):
    __tablename__ = "bot_updates"
    bot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reply: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
