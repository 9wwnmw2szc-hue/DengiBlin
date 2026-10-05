from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import select
from app.config import settings
from app.db import SessionLocal
from app.models import AuditEvent, BrokerConnection, Instrument, Candle, Quote, MarketSnapshot, Portfolio, uid
from app.secrets import SecretStore, SecretError
from app.brokers.tinvest import TInvestSandboxReader, BrokerError


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def connection_status(connection: BrokerConnection | None) -> dict:
    if not connection or connection.status == 'DISCONNECTED':
        return {'status': 'NOT_CONNECTED', 'mode': 'SANDBOX', 'accounts': [], 'account_id': None,
                'last_sync_at': None, 'last_error': None, 'watchlist': [], 'fresh': False}
    return {'status': connection.status, 'mode': connection.mode, 'accounts': connection.accounts,
            'account_id': connection.account_id, 'last_checked_at': aware(connection.last_checked_at).isoformat() if connection.last_checked_at else None,
            'last_sync_at': aware(connection.last_sync_at).isoformat() if connection.last_sync_at else None,
            'last_error': connection.last_error, 'watchlist': connection.watchlist,
            'fresh': bool(connection.status == 'CONNECTED' and connection.last_sync_at and
                0 <= (datetime.now(timezone.utc) - aware(connection.last_sync_at)).total_seconds() <= settings.market_sync_seconds * 2)}


def sync_user(user_id: str, factory=SessionLocal, store: SecretStore | None = None, reader=TInvestSandboxReader):
    """Collect first, then publish atomically only if connection generation still matches."""
    with factory() as db:
        connection = db.get(BrokerConnection, user_id)
        if not connection or connection.status == 'DISCONNECTED' or not connection.account_id:
            return
        generation, reference = connection.generation, connection.secret_ref
        account_id, watchlist = connection.account_id, connection.watchlist
    now = datetime.now(timezone.utc)
    try:
        token = (store or SecretStore()).get(reference, user_id)
        with reader(token) as broker:
            accounts = broker.accounts()
            account = next((a for a in accounts if a['id'] == account_id and a['status'] == 'ACCOUNT_STATUS_OPEN'), None)
            if not account or account['access'] not in {'ACCOUNT_ACCESS_LEVEL_FULL_ACCESS', 'ACCOUNT_ACCESS_LEVEL_READ_ONLY'}:
                raise BrokerError('ACCOUNT_UNAVAILABLE')
            instruments = broker.instruments()
            selected = [i for i in instruments if i['ticker'] in watchlist]
            if not selected:
                raise BrokerError('WATCHLIST_UNAVAILABLE')
            ids = [i['uid'] for i in selected]
            quotes = broker.prices(ids)
            if any(q['at'] > now + timedelta(seconds=5) for q in quotes):
                raise BrokerError('FUTURE_DATA')
            statuses = {i: broker.trading_status(i) for i in ids}
            candles = {i: broker.candles(i, now - timedelta(days=1), now) for i in ids}
            broker_portfolio = broker.portfolio(account_id)
            balances = broker.positions(account_id)
            orders = broker.orders(account_id)
        with factory() as db:
            connection = db.scalar(select(BrokerConnection).where(BrokerConnection.user_id == user_id).with_for_update())
            if not connection or connection.generation != generation or connection.status == 'DISCONNECTED':
                return  # an in-flight request cannot revive a disconnected/replaced connection
            for item in instruments:
                instrument = db.scalar(select(Instrument).where(Instrument.user_id == user_id, Instrument.instrument_uid == item['uid']))
                if instrument is None:
                    instrument = Instrument(user_id=user_id, instrument_uid=item['uid'])
                    db.add(instrument)
                for field in ('figi','ticker','name','lot','currency','exchange','class_code'):
                    setattr(instrument, field, item[field])
                instrument.updated_at = now
            for q in quotes:
                exists = db.scalar(select(Quote).where(Quote.user_id == user_id, Quote.instrument_uid == q['uid'], Quote.source_at == q['at']))
                if exists is None:
                    db.add(Quote(user_id=user_id, instrument_uid=q['uid'], source_at=q['at'], received_at=now, price=Decimal(q['price'])))
                elif exists.price != Decimal(q['price']):
                    raise BrokerError('INCONSISTENT_QUOTE')
            for instrument_uid, history in candles.items():
                for item in history:
                    candle = db.scalar(select(Candle).where(Candle.user_id == user_id, Candle.instrument_uid == instrument_uid,
                                                           Candle.timeframe == '1h', Candle.source_at == item['at']))
                    if candle is None:
                        candle = Candle(user_id=user_id, instrument_uid=instrument_uid, timeframe='1h', source_at=item['at'])
                        db.add(candle)
                    for field in ('open','high','low','close'):
                        setattr(candle, field, Decimal(item[field]))
                    candle.volume, candle.complete = item['volume'], item['complete']
            snapshot = MarketSnapshot(user_id=user_id, account_id=account_id, created_at=now, data={
                'portfolio': broker_portfolio, 'balances': balances, 'orders': orders, 'statuses': statuses,
                'watchlist': watchlist, 'missing_tickers': [ticker for ticker in watchlist if ticker not in {i['ticker'] for i in selected}],
                'transport': 'REST_SNAPSHOT', 'source': 'T_INVEST_SANDBOX',
            })
            db.add(snapshot)
            connection.accounts = accounts
            connection.status = 'CONNECTED'
            connection.last_checked_at = connection.last_sync_at = now
            connection.last_error = None
            db.add(AuditEvent(user_id=user_id, event='MARKET_DATA_SYNCED', details={'instruments': len(instruments),
                'quotes': len(quotes), 'candles': sum(len(v) for v in candles.values()), 'mode': 'SANDBOX'}))
            db.commit()
    except (BrokerError, SecretError) as error:
        with factory() as db:
            connection = db.scalar(select(BrokerConnection).where(BrokerConnection.user_id == user_id).with_for_update())
            if not connection or connection.generation != generation or connection.status == 'DISCONNECTED':
                return
            connection.status = 'ERROR'
            connection.last_error = error.code if isinstance(error, BrokerError) else 'SECRET_UNAVAILABLE'
            connection.last_checked_at = now
            portfolio = db.scalar(select(Portfolio).where(Portfolio.user_id == user_id, Portfolio.mode == 'SANDBOX'))
            if portfolio:
                portfolio.autopilot, portfolio.safe_mode = False, True
            db.add(AuditEvent(user_id=user_id, event='BROKER_SYNC_FAILED', details={'reason': connection.last_error}))
            db.commit()


def queue_sync(cache, user_id: str) -> bool:
    # Debounce and enqueue atomically. No token/account identifiers in Redis.
    return bool(cache.eval("if redis.call('SET',KEYS[1],'1','NX','EX',60) then redis.call('LPUSH',KEYS[2],ARGV[1]); return 1 end; return 0",
                           2, f'market:queued:{user_id}', 'market:queue', user_id))
