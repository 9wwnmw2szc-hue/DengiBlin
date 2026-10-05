"""Encrypted token files outside the business DB. Never exposed through HTTP."""
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4
from cryptography.fernet import Fernet, MultiFernet, InvalidToken
from app.config import settings


class SecretError(Exception):
    def __init__(self):
        super().__init__("SECRET_UNAVAILABLE")


class SecretStore:
    def __init__(self, key_dir: Path | None = None, token_dir: Path | None = None):
        self.key_dir = key_dir or settings.broker_key_dir
        self.token_dir = token_dir or settings.broker_token_dir

    @contextmanager
    def _lock(self, initialize=False):
        if initialize:
            self.key_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.token_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with open(self.key_dir / '.lock', 'a') as lock:
                os.chmod(lock.name, 0o600)
                fcntl.flock(lock, fcntl.LOCK_EX)
                yield
        except (OSError, ValueError, InvalidToken, json.JSONDecodeError, KeyError, TypeError):
            raise SecretError() from None

    def _keys(self, initialize=False):
        path = self.key_dir / 'keys.json'
        if initialize and not path.exists():
            self._atomic(path, json.dumps([Fernet.generate_key().decode()]).encode())
        keys = json.loads(path.read_text())
        if not isinstance(keys, list) or not keys:
            raise SecretError()
        return MultiFernet([Fernet(key.encode()) for key in keys])

    @staticmethod
    def _atomic(path: Path, value: bytes):
        fd, tmp = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _path(self, reference: str) -> Path:
        return self.token_dir / f'{UUID(reference)}.enc'

    def put(self, user_id: str, token: str) -> str:
        if not token or any(c.isspace() for c in token) or not 10 <= len(token) <= 4096:
            raise SecretError()
        reference = str(uuid4())
        with self._lock(initialize=True):
            payload = json.dumps({'user_id': user_id, 'token': token}).encode()
            self._atomic(self._path(reference), self._keys(initialize=True).encrypt(payload))
        return reference

    def get(self, reference: str, user_id: str) -> str:
        with self._lock():
            payload = json.loads(self._keys().decrypt(self._path(reference).read_bytes()))
            if payload['user_id'] != user_id:
                raise SecretError()
            return payload['token']

    def delete(self, reference: str):
        with self._lock():
            self._path(reference).unlink(missing_ok=True)

    def rotate(self):
        # Keep old keys until every ciphertext was rewritten; interrupted rotation is recoverable.
        with self._lock():
            path = self.key_dir / 'keys.json'
            old = json.loads(path.read_text())
            new = Fernet.generate_key().decode()
            self._atomic(path, json.dumps([new, *old]).encode())
            cipher = self._keys()
            for encrypted in self.token_dir.glob('*.enc'):
                self._atomic(encrypted, cipher.rotate(encrypted.read_bytes()))
            self._atomic(path, json.dumps([new]).encode())
