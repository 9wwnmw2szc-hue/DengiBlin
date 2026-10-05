"""Server-local secret enrollment. Broker credentials never enter browser or CLI args."""
import argparse
import getpass
import sys
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.db import SessionLocal
from app.models import User, BrokerConnection, AuditEvent, uid
from app.secrets import SecretStore, SecretError
from app.brokers.tinvest import TInvestSandboxReader, BrokerError


def provision(email: str, token: str, factory=SessionLocal, store: SecretStore | None = None, reader=TInvestSandboxReader):
    store = store or SecretStore()
    with factory() as db:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if not user:
            raise ValueError('USER_NOT_FOUND')
        user_id = user.id
    # Validate only against Sandbox; a production token can never authorize a production call.
    with reader(token) as broker:
        accounts = broker.accounts()
    reference = store.put(user_id, token)
    old_reference = None
    try:
        with factory() as db:
            # Serialize concurrent first enrollment as well as token replacements.
            db.scalar(select(User).where(User.id == user_id).with_for_update())
            connection = db.get(BrokerConnection, user_id)
            if connection:
                old_reference = connection.secret_ref
                event = 'BROKER_TOKEN_REPLACED'
            else:
                connection = BrokerConnection(user_id=user_id)
                db.add(connection)
                event = 'BROKER_CONNECTED'
            connection.secret_ref = reference
            connection.generation = uid()
            connection.mode = 'SANDBOX'
            connection.status = 'ACCOUNT_REQUIRED'
            connection.accounts = accounts
            connection.account_id = None
            connection.last_sync_at = None
            connection.last_checked_at = datetime.now(timezone.utc)
            connection.last_error = None
            db.add(AuditEvent(user_id=user_id, event=event, details={'mode': 'SANDBOX', 'accounts': len(accounts)}))
            db.commit()
    except Exception:
        store.delete(reference)
        raise
    if old_reference:
        store.delete(old_reference)


def main():
    parser = argparse.ArgumentParser(description='MarketBrain Sandbox secret enrollment')
    parser.add_argument('--email')
    parser.add_argument('--rotate-key', action='store_true')
    args = parser.parse_args()
    try:
        if args.rotate_key:
            SecretStore().rotate()
            with SessionLocal() as db:
                users = db.scalars(select(BrokerConnection.user_id)).all()
                for user_id in users:
                    db.add(AuditEvent(user_id=user_id, event='BROKER_ENCRYPTION_KEY_ROTATED', details={}))
                db.commit()
            print('Encryption key rotated.')
            return
        if not args.email:
            parser.error('--email is required')
        if not sys.stdin.isatty():
            parser.error('Use an interactive terminal for hidden token input')
        token = getpass.getpass('T-Invest Sandbox token (hidden): ')
        provision(args.email, token)
        print('Sandbox token validated and encrypted. Select an account in Settings.')
    except (BrokerError, SecretError, ValueError):
        print('Enrollment failed: check Sandbox token, account, and secret storage. No credentials were logged.', file=sys.stderr)
        raise SystemExit(1) from None
    except SQLAlchemyError:
        print('Database unavailable. Enrollment not completed.', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
