from pathlib import Path
from cryptography.fernet import Fernet
import pytest
from app.secrets import SecretStore, SecretError


@pytest.fixture
def store(tmp_path):
    return SecretStore(tmp_path / 'keys', tmp_path / 'tokens')


def test_encryption_and_tenant_binding(store):
    token = 'fixture-token-for-tests-only'
    reference = store.put('user-one', token)
    assert store.get(reference, 'user-one') == token
    assert token.encode() not in store._path(reference).read_bytes()
    assert store._path(reference).stat().st_mode & 0o777 == 0o600
    with pytest.raises(SecretError):
        store.get(reference, 'user-two')


def test_rotation_reencrypts_and_preserves_tokens(store):
    reference = store.put('one', 'fixture-token-for-tests-only')
    before = store._path(reference).read_bytes()
    old_key = (store.key_dir / 'keys.json').read_text()
    store.rotate()
    assert old_key != (store.key_dir / 'keys.json').read_text()
    assert before != store._path(reference).read_bytes()
    assert store.get(reference, 'one') == 'fixture-token-for-tests-only'


def test_missing_and_corrupted_credentials_fail_closed(store):
    with pytest.raises(SecretError):
        store.get('../escape', 'one')
    reference = store.put('one', 'fixture-token-for-tests-only')
    store._path(reference).write_bytes(b'corrupted')
    with pytest.raises(SecretError):
        store.get(reference, 'one')


def test_delete_removes_ciphertext(store):
    reference = store.put('one', 'fixture-token-for-tests-only')
    store.delete(reference)
    with pytest.raises(SecretError):
        store.get(reference, 'one')


def test_interrupted_rotation_keeps_old_ciphertext_readable(store, monkeypatch):
    first = store.put('one','fixture-token-only-one')
    second = store.put('two','fixture-token-only-two')
    atomic = store._atomic
    def interrupted(path, value):
        if path == store._path(second):
            raise OSError('simulated-interruption')
        atomic(path, value)
    monkeypatch.setattr(store,'_atomic',interrupted)
    with pytest.raises(SecretError):
        store.rotate()
    assert store.get(first,'one') == 'fixture-token-only-one'
    assert store.get(second,'two') == 'fixture-token-only-two'
    monkeypatch.setattr(store,'_atomic',atomic)
    store.rotate()
    assert store.get(second,'two') == 'fixture-token-only-two'
