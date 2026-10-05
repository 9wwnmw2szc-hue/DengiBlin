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
