"""Pure risk rules. No network, broker, LLM, or order submission access."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from app.config import Settings


@dataclass(frozen=True)
class BuyProposal:
    equity: Decimal
    cash: Decimal
    invested: Decimal
    company_exposure: Decimal
    price: Decimal
    stop: Decimal
    lot_size: int
    daily_loss_fraction: Decimal = Decimal("0")
    drawdown: Decimal = Decimal("0")
    open_positions: int = 0
    data_age_seconds: int = 0
    market_open: bool = False
    instrument_tradable: bool = False
    broker_healthy: bool = False
    reconciled: bool = False
    unknown_order: bool = False
    safe_mode: bool = True
    asset_class: str = "share"
    liquidity_ok: bool = False
    volatility_ok: bool = False
    correlation_ok: bool = False


@dataclass(frozen=True)
class RiskResult:
    approved: bool
    lots: int
    reasons: tuple[str, ...]


def evaluate_buy(p: BuyProposal, limits: Settings) -> RiskResult:
    numbers = [p.equity, p.cash, p.invested, p.company_exposure, p.price, p.stop,
               p.daily_loss_fraction, p.drawdown]
    if any(not n.is_finite() or n < 0 for n in numbers) or p.open_positions < 0:
        return RiskResult(False, 0, ("INVALID_INPUT",))
    fractions = [limits.risk_per_trade, limits.max_position, limits.max_exposure,
                 limits.max_daily_loss, limits.max_drawdown]
    if (any(not n.is_finite() or not 0 < n <= 1 for n in fractions)
            or not limits.commission_rate.is_finite() or not 0 <= limits.commission_rate < 1
            or limits.max_positions < 1 or limits.max_data_age_seconds < 0):
        return RiskResult(False, 0, ("INVALID_CONFIG",))
    checks = [
        (p.safe_mode, "SAFE_MODE"),
        (p.unknown_order, "UNKNOWN_ORDER"),
        (not p.reconciled, "NOT_RECONCILED"),
        (not p.broker_healthy, "BROKER_UNAVAILABLE"),
        (not p.market_open or not p.instrument_tradable, "MARKET_CLOSED"),
        (p.data_age_seconds < 0 or p.data_age_seconds > limits.max_data_age_seconds, "STALE_DATA"),
        (p.asset_class != "share", "ASSET_NOT_ENABLED"),
        (not p.liquidity_ok, "LIQUIDITY"),
        (not p.volatility_ok, "VOLATILITY"),
        (not p.correlation_ok, "CORRELATION"),
        (p.daily_loss_fraction >= limits.max_daily_loss, "DAILY_LOSS_LIMIT"),
        (p.drawdown >= limits.max_drawdown, "DRAWDOWN_LIMIT"),
        (p.open_positions >= limits.max_positions, "POSITION_COUNT_LIMIT"),
    ]
    reasons = tuple(reason for failed, reason in checks if failed)
    if reasons:
        return RiskResult(False, 0, reasons)
    if p.equity <= 0 or p.price <= 0 or p.stop <= 0 or p.stop >= p.price or p.lot_size < 1:
        return RiskResult(False, 0, ("INVALID_INPUT",))
    fee = limits.commission_rate
    lot_cost = p.price * p.lot_size * (1 + fee)
    lot_risk = ((p.price - p.stop) + fee * (p.price + p.stop)) * p.lot_size
    budget = min(p.cash, p.equity * limits.max_position - p.company_exposure,
                 p.equity * limits.max_exposure - p.invested)
    lots = int(min(budget / lot_cost, p.equity * limits.risk_per_trade / lot_risk)
               .to_integral_value(rounding=ROUND_FLOOR))
    if lots < 1:
        return RiskResult(False, 0, ("LOT_EXCEEDS_LIMITS",))
    return RiskResult(True, lots, ("RISK_APPROVED",))
