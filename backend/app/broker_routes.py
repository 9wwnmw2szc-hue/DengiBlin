from datetime import datetime, timezone
from typing import Annotated
import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, ConfigDict
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession
from app.auth import current_user
from app.db import get_db
from app.models import BrokerConnection, AuditEvent, User, Portfolio, uid, Instrument, Quote, Candle, MarketSnapshot
from app.infrastructure import cache
from app.market_data import connection_status, queue_sync, aware
from app.secrets import SecretStore, SecretError
from app.config import settings
from app.brokers.tinvest import TInvestSandboxReader, BrokerError

router = APIRouter(prefix='/api', tags=['Sandbox data'])
DB = Annotated[DBSession, Depends(get_db)]
Principal = Annotated[User, Depends(current_user)]


def connected(db: DBSession, user: User, lock=False) -> BrokerConnection:
    statement = select(BrokerConnection).where(BrokerConnection.user_id == user.id)
    connection = db.scalar(statement.with_for_update() if lock else statement)
    if not connection or connection.status == 'DISCONNECTED':
        raise HTTPException(409, 'Сначала добавьте Sandbox-токен на сервере')
    return connection


@router.get('/broker')
def broker_status(db: DB, user: Principal):
    return connection_status(db.get(BrokerConnection, user.id))


@router.post('/broker/validate')
def validate_connection(db: DB, user: Principal):
    connection = connected(db, user, lock=True)
    try:
        token = SecretStore().get(connection.secret_ref, user.id)
        with TInvestSandboxReader(token) as broker:
            accounts = broker.accounts()
    except (SecretError, BrokerError) as error:
        connection.status = 'ERROR'
        connection.last_error = error.code if isinstance(error, BrokerError) else 'SECRET_UNAVAILABLE'
        connection.last_checked_at = datetime.now(timezone.utc)
        connection.generation = uid()
        db.add(AuditEvent(user_id=user.id, event='BROKER_VALIDATION_FAILED', details={'reason':connection.last_error}))
        db.commit()
        raise HTTPException(409, 'Sandbox-подключение не прошло проверку')
    connection.accounts = accounts
    accessible = any(a['id'] == connection.account_id and a['status'] == 'ACCOUNT_STATUS_OPEN' and
                     a['access'] in {'ACCOUNT_ACCESS_LEVEL_FULL_ACCESS','ACCOUNT_ACCESS_LEVEL_READ_ONLY'} for a in accounts)
    if not accessible:
        connection.account_id = None
        connection.status = 'ACCOUNT_REQUIRED'
    else:
        connection.status = 'PENDING_SYNC'
    connection.last_checked_at = datetime.now(timezone.utc)
    connection.last_sync_at = None
    connection.last_error = None
    connection.generation = uid()
    db.add(AuditEvent(user_id=user.id, event='BROKER_VALIDATED', details={'mode':'SANDBOX','accounts':len(accounts)}))
    db.commit()
    return connection_status(connection)


class AccountSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    account_id: str = Field(min_length=1, max_length=64)


@router.post('/broker/account')
def select_account(body: AccountSelection, db: DB, user: Principal):
    connection = connected(db, user, lock=True)
    if not any(a['id'] == body.account_id and a['status'] == 'ACCOUNT_STATUS_OPEN'
               and a['access'] in {'ACCOUNT_ACCESS_LEVEL_FULL_ACCESS', 'ACCOUNT_ACCESS_LEVEL_READ_ONLY'} for a in connection.accounts):
        raise HTTPException(400, 'Sandbox-счёт недоступен для чтения')
    connection.account_id = body.account_id
    connection.generation = uid()
    connection.last_sync_at = None
    connection.status = 'PENDING_SYNC'
    connection.last_error = None
    db.add(AuditEvent(user_id=user.id, event='BROKER_ACCOUNT_SELECTED', details={'mode':'SANDBOX'}))
    db.commit()
    try:
        queue_sync(cache, user.id)
    except RedisError:
        raise HTTPException(503, 'Счёт сохранён; очередь недоступна. Повторите обновление данных')
    return connection_status(connection)


class Watchlist(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tickers: list[str] = Field(min_length=1, max_length=5)

    @field_validator('tickers')
    @classmethod
    def validate_tickers(cls, tickers):
        result = list(dict.fromkeys(t.strip().upper() for t in tickers))
        if any(not re.fullmatch(r'[A-Z0-9]{1,16}', ticker) for ticker in result):
            raise ValueError('Некорректный тикер')
        return result


@router.post('/broker/watchlist')
def watchlist(body: Watchlist, db: DB, user: Principal):
    connection = connected(db, user, lock=True)
    connection.watchlist, connection.generation = body.tickers, uid()
    connection.last_sync_at = None
    if connection.account_id:
        connection.status = 'PENDING_SYNC'
    db.add(AuditEvent(user_id=user.id, event='WATCHLIST_CHANGED', details={'tickers': body.tickers}))
    db.commit()
    return connection_status(connection)


@router.post('/broker/sync', status_code=202)
def request_sync(db: DB, user: Principal):
    connection = connected(db, user)
    if not connection.account_id:
        raise HTTPException(409, 'Выберите Sandbox-счёт')
    try:
        queued = queue_sync(cache, user.id)
    except RedisError:
        raise HTTPException(503, 'Очередь временно недоступна')
    return {'queued': queued, 'message': 'Обновление поставлено в очередь' if queued else 'Обновление уже запрошено; повтор доступен через минуту'}


@router.post('/broker/disconnect')
def disconnect(db: DB, user: Principal):
    connection = connected(db, user, lock=True)
    reference = connection.secret_ref
    connection.status = 'DISCONNECTED'
    connection.generation = uid()
    connection.account_id = None
    connection.accounts = []
    connection.last_sync_at = None
    connection.last_error = None
    portfolio = db.scalar(select(Portfolio).where(Portfolio.user_id == user.id, Portfolio.mode == 'SANDBOX').with_for_update())
    if portfolio:
        portfolio.autopilot, portfolio.safe_mode = False, True
    db.add(AuditEvent(user_id=user.id, event='BROKER_DISCONNECTED', details={'mode': 'SANDBOX'}))
    db.commit()
    deleted = True
    try:
        SecretStore().delete(reference)
    except SecretError:
        deleted = False
        db.add(AuditEvent(user_id=user.id, event='SECRET_DELETE_FAILED', details={}))
        db.commit()
    return {'status':'NOT_CONNECTED', 'secret_removed': deleted,
            'message': ('Подключение отключено. Для отзыва токена у брокера удалите его в настройках T-Invest.' if deleted else
                        'Подключение отключено, но серверную копию токена удалить не удалось. Проверьте хранилище и отзовите токен в настройках T-Invest.')}


@router.get('/market')
def market(db: DB, user: Principal):
    connection = db.get(BrokerConnection, user.id)
    status = connection_status(connection)
    if not connection or connection.status == 'DISCONNECTED':
        return {'connection': status, 'instruments': [], 'snapshot': None}
    instruments = db.scalars(select(Instrument).where(Instrument.user_id == user.id,
                            Instrument.ticker.in_(connection.watchlist)).order_by(Instrument.ticker)).all()
    snapshot = db.scalar(select(MarketSnapshot).where(MarketSnapshot.user_id == user.id,
                         MarketSnapshot.account_id == connection.account_id).order_by(MarketSnapshot.created_at.desc()).limit(1)) if connection.account_id else None
    now = datetime.now(timezone.utc)
    rows = []
    for instrument in instruments:
        quote = db.scalar(select(Quote).where(Quote.user_id == user.id, Quote.instrument_uid == instrument.instrument_uid)
                          .order_by(Quote.source_at.desc()).limit(1))
        age = int((now - aware(quote.source_at)).total_seconds()) if quote else None
        rows.append({'uid':instrument.instrument_uid, 'figi':instrument.figi, 'ticker':instrument.ticker,
            'name':instrument.name, 'lot':instrument.lot, 'currency':instrument.currency,
            'price': str(quote.price) if quote else None, 'quote_at':aware(quote.source_at).isoformat() if quote else None,
            'quote_id':quote.id if quote else None,
            'age_seconds':age, 'fresh':bool(status['fresh'] and age is not None and 0 <= age <= settings.quote_freshness_seconds),
            'status':snapshot.data.get('statuses', {}).get(instrument.instrument_uid, {}) if snapshot else {}})
    return {'connection':status, 'instruments':rows, 'snapshot': {
        'id':snapshot.id, 'at':aware(snapshot.created_at).isoformat(), **snapshot.data} if snapshot else None}


@router.get('/market/{instrument_uid}/candles')
def candle_history(instrument_uid: str, db: DB, user: Principal):
    instrument = db.scalar(select(Instrument).where(Instrument.user_id == user.id, Instrument.instrument_uid == instrument_uid))
    if not instrument:
        raise HTTPException(404, 'Инструмент не найден')
    candles = db.scalars(select(Candle).where(Candle.user_id == user.id, Candle.instrument_uid == instrument_uid)
                         .order_by(Candle.source_at.desc()).limit(168)).all()
    return {'ticker':instrument.ticker, 'timeframe':'1h', 'candles':[
        {'id':c.id, 'at':aware(c.source_at).isoformat(), 'open':str(c.open),'high':str(c.high),'low':str(c.low),
         'close':str(c.close),'volume':str(c.volume),'complete':c.complete} for c in reversed(candles)]}
