from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError
import pytest
from app.db import Base, get_db
from app.main import app, cache
from app.models import AuditEvent, Session, User, Portfolio


@pytest.fixture
def client(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(cache, 'eval', lambda *a: 1)
    monkeypatch.setattr(cache, 'get', lambda *a: None)
    with TestClient(app, base_url='https://testserver', headers={'origin': 'http://localhost:3000'}) as c:
        yield c, factory
    app.dependency_overrides.clear()
    engine.dispose()


def register(c, email='one@example.com'):
    return c.post('/api/auth/register', json={'email': email, 'password': 'a-strong-password-849!'})


def test_registration_creates_real_persisted_sandbox(client):
    c, factory = client
    assert register(c).status_code == 201
    dashboard = c.get('/api/dashboard').json()
    assert dashboard['portfolio']['cash'] == '1000.00000000'
    assert dashboard['safe_mode'] and not dashboard['real_enabled']
    cookie = c.cookies.get('mb_session')
    with factory() as db:
        user = db.scalar(select(User))
        assert user.role == 'USER' and user.password_hash.startswith('$argon2')
        assert db.scalar(select(Session)).token_hash != cookie


def test_csrf_blocks_cross_origin(client):
    c, _ = client
    assert c.post('/api/auth/register', headers={'origin': 'https://evil.example'}, json={'email':'one@example.com','password':'a-strong-password-849!'}).status_code == 403


def test_unavailable_redis_blocks_writes(client, monkeypatch):
    c, _ = client
    def fail(*args):
        raise ConnectionError()
    monkeypatch.setattr(cache, 'eval', fail)
    assert register(c).status_code == 503


def test_tenant_isolation(client):
    c, _ = client
    register(c)
    c.post('/api/sandbox/balance', json={'amount': '2500.01'})
    c.post('/api/auth/logout', json={})
    assert c.get('/api/dashboard').status_code == 401
    register(c, 'two@example.com')
    d = c.get('/api/dashboard').json()
    assert d['portfolio']['cash'] == '1000.00000000'
    assert len(d['events']) == 1


def test_autopilot_never_starts_with_missing_data(client):
    c, factory = client
    register(c)
    assert c.post('/api/autopilot/start', json={}).status_code == 409
    assert c.post('/api/real/activate', json={}).status_code == 403
    d = c.get('/api/dashboard').json()
    assert d['decisions'][0]['action'] == 'SKIP'
    with factory() as db:
        assert not db.scalar(select(Portfolio)).autopilot
        assert db.scalar(select(AuditEvent).where(AuditEvent.event=='AUTOPILOT_START_REJECTED'))


def test_login_and_revocation(client):
    c, _ = client
    register(c)
    c.post('/api/auth/logout', json={})
    assert c.post('/api/auth/login', json={'email':'one@example.com','password':'incorrect-password'}).status_code == 401
    assert c.post('/api/auth/login', json={'email':'one@example.com','password':'a-strong-password-849!'}).status_code == 200
    assert c.get('/api/dashboard').status_code == 200


def test_rate_limit(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(cache, 'eval', lambda *a: 31)
    assert register(c).status_code == 429


def add_connection(factory):
    from app.models import BrokerConnection, uid
    with factory() as db:
        user = db.scalar(select(User).where(User.email=='one@example.com'))
        connection = BrokerConnection(user_id=user.id,secret_ref=uid(),account_id=None,
            accounts=[{'id':'my-sandbox','name':'Test account','status':'ACCOUNT_STATUS_OPEN','access':'ACCOUNT_ACCESS_LEVEL_READ_ONLY'}])
        db.add(connection); db.commit()
        return user.id


def test_broker_requires_authentication_and_never_exposes_token(client):
    c, factory = client
    assert c.get('/api/broker').status_code == 401
    register(c)
    add_connection(factory)
    status = c.get('/api/broker').json()
    assert status['mode'] == 'SANDBOX' and status['status'] == 'ACCOUNT_REQUIRED'
    assert 'token' not in status and 'secret_ref' not in status


def test_account_selection_cannot_use_unlisted_account(client):
    c, factory = client
    register(c); add_connection(factory)
    assert c.post('/api/broker/account',json={'account_id':'another-user-account'}).status_code == 400
    assert c.post('/api/broker/account',json={'account_id':'my-sandbox'}).status_code == 200
    assert c.get('/api/broker').json()['status'] == 'PENDING_SYNC'
    assert c.post('/api/broker/sync',json={}).status_code == 202


def test_watchlist_limits_and_validation(client):
    c, factory = client
    register(c); add_connection(factory)
    assert c.post('/api/broker/watchlist',json={'tickers':['sber','SBER','gazp']}).json()['watchlist'] == ['SBER','GAZP']
    assert c.post('/api/broker/watchlist',json={'tickers':['../../token']}).status_code == 422
    assert c.post('/api/broker/watchlist',json={'tickers':['A','B','C','D','E','F']}).status_code == 422


def test_disconnect_blocks_connection_and_stops_autopilot(client, monkeypatch):
    from app.models import BrokerConnection
    from app import broker_routes
    c, factory = client
    register(c); add_connection(factory)
    deleted = []
    class Store:
        def delete(self, reference): deleted.append(reference)
    monkeypatch.setattr(broker_routes,'SecretStore',Store)
    result = c.post('/api/broker/disconnect',json={})
    assert result.status_code == 200 and result.json()['secret_removed'] and deleted
    assert c.get('/api/broker').json()['status'] == 'NOT_CONNECTED'
    assert c.get('/api/market').json()['instruments'] == []
    assert c.post('/api/broker/sync',json={}).status_code == 409


def test_market_history_is_tenant_scoped(client):
    from app.models import Instrument, Quote, Candle
    from datetime import datetime,timezone,timedelta
    c, factory = client
    register(c); user_id = add_connection(factory)
    with factory() as db:
        db.add(Instrument(user_id=user_id,instrument_uid='fixture-uid',figi='fixture',ticker='SBER',name='Test',lot=10,currency='rub',exchange='MOEX',class_code='TQBR'))
        db.add(Quote(user_id=user_id,instrument_uid='fixture-uid',source_at=datetime.now(timezone.utc)-timedelta(hours=1),price=100))
        db.add(Candle(user_id=user_id,instrument_uid='fixture-uid',source_at=datetime.now(timezone.utc)-timedelta(hours=2),open=100,high=101,low=99,close=100,volume=10,complete=True))
        db.commit()
    mine = c.get('/api/market').json()
    assert mine['instruments'][0]['price'] == '100.000000000'
    assert not mine['instruments'][0]['fresh']
    assert c.get('/api/market/fixture-uid/candles').json()['candles'][0]['complete']
    c.post('/api/auth/logout',json={}); register(c,'two@example.com')
    assert c.get('/api/market').json()['instruments'] == []
    assert c.get('/api/market/fixture-uid/candles').status_code == 404


def test_validation_refreshes_accounts_without_exposing_secrets(client, monkeypatch):
    from app import broker_routes
    from app.models import BrokerConnection
    c, factory = client
    register(c); user_id=add_connection(factory)
    class Store:
        def get(self,*args): return 'fixture-token-only'
    class Reader:
        def __init__(self,token): assert token == 'fixture-token-only'
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def accounts(self): return [{'id':'new-sandbox','name':'Fixture','status':'ACCOUNT_STATUS_OPEN','access':'ACCOUNT_ACCESS_LEVEL_READ_ONLY'}]
    monkeypatch.setattr(broker_routes,'SecretStore',Store)
    monkeypatch.setattr(broker_routes,'TInvestSandboxReader',Reader)
    with factory() as db:
        connection=db.get(BrokerConnection,user_id)
        generation=connection.generation
    result=c.post('/api/broker/validate',json={})
    assert result.status_code == 200 and result.json()['accounts'][0]['id'] == 'new-sandbox'
    assert 'fixture-token-only' not in result.text
    with factory() as db:
        assert db.get(BrokerConnection,user_id).generation != generation


def test_connected_data_does_not_enable_autopilot(client):
    from app.models import BrokerConnection
    from datetime import datetime, timezone
    c, factory=client
    register(c); user_id=add_connection(factory)
    with factory() as db:
        connection=db.get(BrokerConnection,user_id)
        connection.status='CONNECTED'; connection.last_sync_at=datetime.now(timezone.utc); db.commit()
    assert c.post('/api/autopilot/start',json={}).status_code == 409
    decision=c.get('/api/dashboard').json()['decisions'][0]
    assert decision['reason'] == 'TRADING_LOOP_NOT_READY'
    assert decision['evidence']['broker'] == 'CONNECTED'
    assert decision['at'].endswith('+00:00')
