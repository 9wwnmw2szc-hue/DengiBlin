"""Sandbox broker references and persistent normalized market history."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    user = lambda: sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False)
    identifier = lambda: sa.Column('id', sa.String(36), primary_key=True)
    op.create_table('broker_connections', sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('secret_ref', sa.String(36), nullable=False), sa.Column('generation', sa.String(36), nullable=False),
        sa.Column('mode', sa.String(16), nullable=False), sa.Column('status', sa.String(32), nullable=False),
        sa.Column('accounts', sa.JSON(), nullable=False), sa.Column('account_id', sa.String(64)),
        sa.Column('watchlist', sa.JSON(), nullable=False), sa.Column('last_checked_at', sa.DateTime(timezone=True)),
        sa.Column('last_sync_at', sa.DateTime(timezone=True)), sa.Column('last_error', sa.String(64)))
    op.create_table('instruments', identifier(), user(), sa.Column('instrument_uid', sa.String(64), nullable=False),
        sa.Column('figi', sa.String(32), nullable=False), sa.Column('ticker', sa.String(32), nullable=False),
        sa.Column('name', sa.String(256), nullable=False), sa.Column('lot', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(8), nullable=False), sa.Column('exchange', sa.String(64), nullable=False),
        sa.Column('class_code', sa.String(16), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'instrument_uid'))
    op.create_table('candles', identifier(), user(), sa.Column('instrument_uid', sa.String(64), nullable=False),
        sa.Column('timeframe', sa.String(8), nullable=False), sa.Column('source_at', sa.DateTime(timezone=True), nullable=False),
        *[sa.Column(field, sa.Numeric(24,9), nullable=False) for field in ('open','high','low','close')],
        sa.Column('volume', sa.BigInteger(), nullable=False), sa.Column('complete', sa.Boolean(), nullable=False),
        sa.UniqueConstraint('user_id','instrument_uid','timeframe','source_at'))
    op.create_table('quotes', identifier(), user(), sa.Column('instrument_uid', sa.String(64), nullable=False),
        sa.Column('source_at', sa.DateTime(timezone=True), nullable=False), sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('price', sa.Numeric(24,9), nullable=False), sa.UniqueConstraint('user_id','instrument_uid','source_at'))
    op.create_table('market_snapshots', identifier(), user(), sa.Column('mode', sa.String(16), nullable=False),
        sa.Column('account_id', sa.String(64), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False))
    for table in ('instruments','candles','quotes','market_snapshots'):
        op.create_index(f'ix_{table}_user_id', table, ['user_id'])


def downgrade():
    for table in ('market_snapshots','quotes','candles','instruments','broker_connections'):
        op.drop_table(table)
