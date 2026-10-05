import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session as DBSession
from app.auth import COOKIE, create_session, current_user, digest, hasher, verify_password
from app.config import settings
from app.db import get_db
from app.models import AuditEvent, Decision, Portfolio, Session, Subscription, User

app = FastAPI(title="MarketBrain", version="0.1.0-foundation")
cache = Redis.from_url(settings.redis_url, decode_responses=True,
                       socket_connect_timeout=2, socket_timeout=2)
log = logging.getLogger("marketbrain")
logging.basicConfig(level=logging.INFO, format='{"level":"%(levelname)s","message":"%(message)s"}')
DB = Annotated[DBSession, Depends(get_db)]
Principal = Annotated[User, Depends(current_user)]


@app.middleware("http")
async def security(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("origin") != settings.app_origin:
            return JSONResponse({"detail": "Origin не разрешён"}, status_code=403)
        # Redis is mandatory for writes; no fail-open rate limit.
        try:
            key = f"rate:{request.client.host}:{int(time.time() // 60)}"
            count = cache.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],120) end; return n", 1, key)
            if count > 30:
                return JSONResponse({"detail": "Слишком много запросов"}, status_code=429)
        except RedisError:
            return JSONResponse({"detail": "Сервис временно недоступен"}, status_code=503)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


def audit(db: DBSession, user: User, event: str, details: dict | None = None):
    db.add(AuditEvent(user_id=user.id, event=event, details=details or {}))


def portfolio(db: DBSession, user: User, lock: bool = False) -> Portfolio:
    query = select(Portfolio).where(Portfolio.user_id == user.id, Portfolio.mode == "SANDBOX")
    p = db.scalar(query.with_for_update() if lock else query)
    if not p:
        raise HTTPException(409, "Sandbox не инициализирован")
    return p


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        value = value.strip().lower()
        if value.count("@") != 1 or "." not in value.split("@")[1] or any(c.isspace() for c in value):
            raise ValueError("Некорректный email")
        return value


@app.get("/health/live")
def live():
    return {"status": "ok", "version": app.version}


@app.get("/health/ready")
def ready(db: DB):
    try:
        db.execute(text("SELECT 1"))
        cache.ping()
        heartbeat = cache.get("worker:heartbeat")
        if not heartbeat or time.time() - float(heartbeat) > 45:
            raise HTTPException(503, "Worker недоступен")
    except (SQLAlchemyError, RedisError):
        raise HTTPException(503, "Зависимости недоступны")
    return {"status": "ready", "database": "ok", "redis": "ok", "worker": "ok"}


@app.post("/api/auth/register", status_code=201)
def register(body: Credentials, response: Response, db: DB):
    # OWNER must be provisioned out of band after verifying identity.
    user = User(email=body.email, password_hash=hasher.hash(body.password), role="USER")
    db.add(user)
    try:
        db.flush()
        db.add(Portfolio(user_id=user.id))
        db.add(Subscription(user_id=user.id))
        audit(db, user, "REGISTER")
        create_session(db, user, response)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Регистрация с этим email недоступна")
    return {"email": user.email, "role": user.role}


@app.post("/api/auth/login")
def login(body: Credentials, response: Response, db: DB):
    user = db.scalar(select(User).where(User.email == body.email))
    # Run the same expensive verifier for an unknown email.
    encoded = user.password_hash if user else DUMMY_PASSWORD_HASH
    if not verify_password(encoded, body.password) or not user:
        raise HTTPException(401, "Неверный email или пароль")
    create_session(db, user, response)
    audit(db, user, "LOGIN")
    db.commit()
    return {"email": user.email, "role": user.role}


DUMMY_PASSWORD_HASH = hasher.hash("not-a-user-password-374390")


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, db: DB, user: Principal):
    db.delete(db.get(Session, digest(request.cookies[COOKIE])))
    audit(db, user, "LOGOUT")
    db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard(db: DB, user: Principal):
    p = portfolio(db, user)
    events = db.scalars(select(AuditEvent).where(AuditEvent.user_id == user.id)
                        .order_by(AuditEvent.created_at.desc(), AuditEvent.id).limit(30)).all()
    decisions = db.scalars(select(Decision).where(Decision.user_id == user.id)
                           .order_by(Decision.created_at.desc()).limit(20)).all()
    try:
        heartbeat = cache.get("worker:heartbeat")
        worker_ok = bool(heartbeat and time.time() - float(heartbeat) < 45)
    except RedisError:
        worker_ok = False
    return {
        "user": {"email": user.email, "role": user.role},
        "mode": "SANDBOX", "real_enabled": False,
        "portfolio": {"equity": str(p.cash), "cash": str(p.cash), "invested": "0",
                      "initial_capital": str(p.initial_capital), "positions": []},
        "autopilot": "STOPPED", "safe_mode": True,
        "broker": "NOT_CONNECTED", "market": "UNKNOWN", "worker_healthy": worker_ok,
        "blockers": ["T-Invest не подключён", "Нет подтверждённых рыночных данных",
                     "Торговый цикл ещё не реализован"],
        "risk": {"trade": str(settings.risk_per_trade), "position": str(settings.max_position),
                 "exposure": str(settings.max_exposure), "daily_loss": str(settings.max_daily_loss),
                 "drawdown": str(settings.max_drawdown)},
        "events": [{"id": e.id, "at": e.created_at.isoformat(), "event": e.event, "details": e.details} for e in events],
        "decisions": [{"id": d.id, "at": d.created_at.isoformat(), "action": d.action,
                       "reason": d.reason, "evidence": d.evidence} for d in decisions],
    }


class Balance(BaseModel):
    amount: Decimal = Field(gt=0, le=Decimal("100000000"), decimal_places=2)


@app.post("/api/sandbox/balance")
def balance(body: Balance, db: DB, user: Principal):
    p = portfolio(db, user, lock=True)
    if p.autopilot:
        raise HTTPException(409, "Сначала остановите Autopilot")
    previous = str(p.cash)
    p.cash = p.initial_capital = body.amount
    audit(db, user, "SANDBOX_BALANCE_CHANGED", {"previous": previous, "amount": str(body.amount)})
    db.commit()
    return {"cash": str(p.cash)}


@app.post("/api/autopilot/start")
def start(db: DB, user: Principal):
    portfolio(db, user, lock=True)
    audit(db, user, "AUTOPILOT_START_REJECTED", {"reason": "DATA_PIPELINE_NOT_READY"})
    db.add(Decision(user_id=user.id, action="SKIP", reason="DATA_PIPELINE_NOT_READY",
                    evidence={"broker": "NOT_CONNECTED", "market": "UNKNOWN"}))
    db.commit()
    raise HTTPException(409, "Autopilot заблокирован: нужны T-Invest, данные и проверенный торговый цикл")


@app.post("/api/autopilot/stop")
def stop(db: DB, user: Principal):
    p = portfolio(db, user, lock=True)
    p.autopilot = False
    audit(db, user, "AUTOPILOT_STOP")
    db.commit()
    return {"status": "STOPPED"}


@app.post("/api/real/activate")
def real(user: Principal):
    raise HTTPException(403, "REAL недоступен до завершения paper test и отдельного разрешения владельца")
