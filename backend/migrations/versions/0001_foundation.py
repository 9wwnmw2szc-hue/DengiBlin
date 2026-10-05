"""Initial tenant-owned foundation tables; trading schemas follow separately."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users", sa.Column("id", sa.String(36), primary_key=True), sa.Column("email", sa.String(254), nullable=False, unique=True), sa.Column("password_hash", sa.String(512), nullable=False), sa.Column("role", sa.String(16), nullable=False), sa.Column("email_verified", sa.Boolean(), nullable=False))
    op.create_table("sessions", sa.Column("token_hash", sa.String(64), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("portfolios", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("mode", sa.String(16), nullable=False), sa.Column("cash", sa.Numeric(20,8), nullable=False), sa.Column("initial_capital", sa.Numeric(20,8), nullable=False), sa.Column("autopilot", sa.Boolean(), nullable=False), sa.Column("safe_mode", sa.Boolean(), nullable=False), sa.UniqueConstraint("user_id", "mode"))
    op.create_table("audit_log", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("event", sa.String(64), nullable=False), sa.Column("details", sa.JSON(), nullable=False))
    op.create_table("decisions", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("mode", sa.String(16), nullable=False), sa.Column("action", sa.String(16), nullable=False), sa.Column("reason", sa.String(256), nullable=False), sa.Column("evidence", sa.JSON(), nullable=False))
    op.create_table("orders", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("mode", sa.String(16), nullable=False), sa.Column("idempotency_key", sa.String(128), nullable=False), sa.Column("decision_id", sa.String(36), sa.ForeignKey("decisions.id"), nullable=False), sa.Column("state", sa.String(32), nullable=False), sa.Column("instrument_uid", sa.String(64), nullable=False), sa.Column("lots", sa.Integer(), nullable=False), sa.UniqueConstraint("user_id", "mode", "idempotency_key"))
    op.create_table("subscriptions", sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True), sa.Column("plan", sa.String(32), nullable=False), sa.Column("entitlements", sa.JSON(), nullable=False))
    for table in ("sessions", "portfolios", "audit_log", "decisions", "orders"):
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])


def downgrade():
    for table in ("subscriptions", "orders", "decisions", "audit_log", "portfolios", "sessions", "users"):
        op.drop_table(table)
