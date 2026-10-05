import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, DateTime, Numeric, Boolean, ForeignKey, JSON, UniqueConstraint, BigInteger
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


def uid():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(16), default="USER")
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)


class Session(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Portfolio(Base):
    __tablename__ = "portfolios"
    __table_args__ = (UniqueConstraint("user_id", "mode"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    mode: Mapped[str] = mapped_column(String(16), default="SANDBOX")
    cash: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("1000"))
    initial_capital: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("1000"))
    autopilot: Mapped[bool] = mapped_column(Boolean, default=False)
    safe_mode: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditEvent(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    mode: Mapped[str] = mapped_column(String(16), default="SANDBOX")
    action: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(256))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("user_id", "mode", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    mode: Mapped[str] = mapped_column(String(16), default="SANDBOX")
    idempotency_key: Mapped[str] = mapped_column(String(128))
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"))
    state: Mapped[str] = mapped_column(String(32), default="CREATED")
    instrument_uid: Mapped[str] = mapped_column(String(64))
    lots: Mapped[int]


class Subscription(Base):
    __tablename__ = "subscriptions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    plan: Mapped[str] = mapped_column(String(32), default="Free")
    entitlements: Mapped[list] = mapped_column(JSON, default=list)


class BrokerConnection(Base):
    __tablename__ = "broker_connections"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    secret_ref: Mapped[str] = mapped_column(String(36))
    generation: Mapped[str] = mapped_column(String(36), default=uid)
    mode: Mapped[str] = mapped_column(String(16), default="SANDBOX")
    status: Mapped[str] = mapped_column(String(32), default="ACCOUNT_REQUIRED")
    accounts: Mapped[list] = mapped_column(JSON, default=list)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    watchlist: Mapped[list] = mapped_column(JSON, default=lambda: ["SBER", "GAZP", "LKOH", "YDEX", "T"])
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("user_id", "instrument_uid"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    instrument_uid: Mapped[str] = mapped_column(String(64))
    figi: Mapped[str] = mapped_column(String(32))
    ticker: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(256))
    lot: Mapped[int]
    currency: Mapped[str] = mapped_column(String(8))
    exchange: Mapped[str] = mapped_column(String(64))
    class_code: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (UniqueConstraint("user_id", "instrument_uid", "timeframe", "source_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    instrument_uid: Mapped[str] = mapped_column(String(64))
    timeframe: Mapped[str] = mapped_column(String(8), default="1h")
    source_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open: Mapped[Decimal] = mapped_column(Numeric(24, 9))
    high: Mapped[Decimal] = mapped_column(Numeric(24, 9))
    low: Mapped[Decimal] = mapped_column(Numeric(24, 9))
    close: Mapped[Decimal] = mapped_column(Numeric(24, 9))
    volume: Mapped[int] = mapped_column(BigInteger)
    complete: Mapped[bool] = mapped_column(Boolean)


class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = (UniqueConstraint("user_id", "instrument_uid", "source_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    instrument_uid: Mapped[str] = mapped_column(String(64))
    source_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    price: Mapped[Decimal] = mapped_column(Numeric(24, 9))


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    mode: Mapped[str] = mapped_column(String(16), default="SANDBOX")
    account_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    data: Mapped[dict] = mapped_column(JSON)
