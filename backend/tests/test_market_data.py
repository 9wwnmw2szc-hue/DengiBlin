from datetime import datetime, timezone, timedelta
from decimal import Decimal
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest
from app.db import Base
from app.models import User, Portfolio, BrokerConnection, Candle, Quote, MarketSnapshot, AuditEvent, uid
from app.market_data import sync_user, connection_status
from app.provision_token import provision
from app.brokers.tinvest import BrokerError
from app.secrets import SecretStore


@pytest.fixture
def state(tmp_path):
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine,expire_on_commit=False)
    with factory() as db:
        user = User(email='pipeline@example.com',password_hash='fixture-hash')
        db.add(user); db.flush()
        db.add(Portfolio(user_id=user.id)); db.commit()
        user_id = user.id
    store = SecretStore(tmp_path/'keys',tmp_path/'tokens')
    return factory, store, user_id


class FixtureReader:
    """Explicit test fixtures; never used by application runtime."""
    at = datetime.now(timezone.utc).replace(microsecond=0)
    def __init__(self, token):
        assert token == 'fixture-token-only'
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def accounts(self): return [{'id':'sandbox-account','name':'Fixture','status':'ACCOUNT_STATUS_OPEN','access':'ACCOUNT_ACCESS_LEVEL_READ_ONLY'}]
    def instruments(self): return [{'uid':'fixture-uid','figi':'fixture-figi','ticker':'SBER','name':'Fixture','lot':10,'currency':'rub','exchange':'MOEX','class_code':'TQBR'}]
    def prices(self, ids): return [{'uid':'fixture-uid','price':'100.000000001','at':self.at}]
    def trading_status(self, instrument_id): return {'status':'SECURITY_TRADING_STATUS_NORMAL_TRADING','api_available':True,'market_orders':True}
    def candles(self, instrument_id, start, end): return [{'at':self.at-timedelta(hours=1),'open':'100','high':'102','low':'99','close':'101','volume':100,'complete':True}]
    def portfolio(self, account_id): return {'account_id':account_id,'equity':'1000','currency':'rub','positions':[]}
    def positions(self, account_id): return {'money':[{'currency':'rub','amount':'1000'}],'blocked':[]}
    def orders(self, account_id): return []


def enroll(state):
    factory, store, user_id = state
    provision('pipeline@example.com','fixture-token-only',factory,store,FixtureReader)
    with factory() as db:
        connection = db.get(BrokerConnection,user_id)
        connection.account_id = 'sandbox-account'
        connection.status = 'PENDING_SYNC'
        db.commit()


def test_persistence_and_idempotent_history(state):
    factory, store, user_id = state
    enroll(state)
    sync_user(user_id,factory,store,FixtureReader)
    sync_user(user_id,factory,store,FixtureReader)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Quote)) == 1
        assert db.scalar(select(func.count()).select_from(Candle)) == 1
        assert db.scalar(select(func.count()).select_from(MarketSnapshot)) == 2
        assert db.scalar(select(Quote)).price == Decimal('100.000000001')
        assert db.get(BrokerConnection,user_id).status == 'CONNECTED'
        assert db.scalar(select(Portfolio)).safe_mode


def test_partial_failure_never_publishes_partial_snapshot(state):
    factory, store, user_id = state
    enroll(state)
    class FailsAtOrders(FixtureReader):
        def orders(self, account_id): raise BrokerError('BROKER_UNAVAILABLE')
    sync_user(user_id,factory,store,FailsAtOrders)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Quote)) == 0
        assert db.scalar(select(func.count()).select_from(MarketSnapshot)) == 0
        assert db.get(BrokerConnection,user_id).status == 'ERROR'
        assert db.get(BrokerConnection,user_id).last_error == 'BROKER_UNAVAILABLE'
        assert not db.scalar(select(Portfolio)).autopilot


def test_in_flight_sync_cannot_revive_disconnected_connection(state):
    factory, store, user_id = state
    enroll(state)
    class DisconnectDuringRead(FixtureReader):
        def orders(self, account_id):
            with factory() as db:
                c = db.get(BrokerConnection,user_id)
                c.status = 'DISCONNECTED'; c.generation = uid(); db.commit()
            return []
    sync_user(user_id,factory,store,DisconnectDuringRead)
    with factory() as db:
        assert db.get(BrokerConnection,user_id).status == 'DISCONNECTED'
        assert db.scalar(select(func.count()).select_from(MarketSnapshot)) == 0


def test_invalid_replacement_preserves_existing_token(state):
    factory, store, user_id = state
    enroll(state)
    with factory() as db:
        original = db.get(BrokerConnection,user_id).secret_ref
    class Rejected(FixtureReader):
        def accounts(self): raise BrokerError('TOKEN_REJECTED')
    with pytest.raises(BrokerError):
        provision('pipeline@example.com','fixture-token-only',factory,store,Rejected)
    with factory() as db:
        assert db.get(BrokerConnection,user_id).secret_ref == original
    assert store.get(original,user_id) == 'fixture-token-only'


def test_status_never_exposes_secret_reference(state):
    factory, store, user_id = state
    enroll(state)
    with factory() as db:
        status = connection_status(db.get(BrokerConnection,user_id))
    assert 'secret_ref' not in status and 'token' not in status


def test_expired_connection_is_not_fresh(state):
    factory, store, user_id = state
    enroll(state)
    with factory() as db:
        c = db.get(BrokerConnection,user_id)
        c.status='CONNECTED'; c.last_sync_at=datetime.now(timezone.utc)-timedelta(hours=1)
        assert not connection_status(c)['fresh']
