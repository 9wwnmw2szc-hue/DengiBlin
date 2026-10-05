from dataclasses import replace
from decimal import Decimal as D
import pytest
from app.config import Settings
from app.risk import BuyProposal, evaluate_buy


@pytest.fixture
def proposal():
    return BuyProposal(equity=D('100000'), cash=D('100000'), invested=D('0'),
        company_exposure=D('0'), price=D('100'), stop=D('95'), lot_size=10,
        market_open=True, instrument_tradable=True, broker_healthy=True, reconciled=True,
        safe_mode=False, liquidity_ok=True, volatility_ok=True, correlation_ok=True)


def test_small_balance_cannot_afford_lot(proposal):
    p = replace(proposal, equity=D('1000'), cash=D('1000'))
    result = evaluate_buy(p, Settings())
    assert not result.approved and result.reasons == ('LOT_EXCEEDS_LIMITS',)


def test_position_sizing_obeys_fee_and_risk(proposal):
    limits = Settings()
    result = evaluate_buy(proposal, limits)
    assert result.approved and result.lots == 14
    cost = result.lots * proposal.lot_size * proposal.price * (1 + limits.commission_rate)
    risk = result.lots * proposal.lot_size * ((proposal.price-proposal.stop) + limits.commission_rate*(proposal.price+proposal.stop))
    assert cost <= proposal.equity * limits.max_position
    assert risk <= proposal.equity * limits.risk_per_trade


@pytest.mark.parametrize('change,reason', [
    ({'safe_mode': True}, 'SAFE_MODE'), ({'unknown_order': True}, 'UNKNOWN_ORDER'),
    ({'reconciled': False}, 'NOT_RECONCILED'), ({'broker_healthy': False}, 'BROKER_UNAVAILABLE'),
    ({'data_age_seconds': 31}, 'STALE_DATA'), ({'market_open': False}, 'MARKET_CLOSED'),
    ({'daily_loss_fraction': D('0.02')}, 'DAILY_LOSS_LIMIT'),
    ({'drawdown': D('0.08')}, 'DRAWDOWN_LIMIT'), ({'asset_class': 'future'}, 'ASSET_NOT_ENABLED'),
    ({'liquidity_ok': False}, 'LIQUIDITY'), ({'correlation_ok': False}, 'CORRELATION'),
    ({'volatility_ok': False}, 'VOLATILITY'), ({'open_positions': 4}, 'POSITION_COUNT_LIMIT'),
])
def test_blockers_fail_closed(proposal, change, reason):
    result = evaluate_buy(replace(proposal, **change), Settings())
    assert not result.approved and result.lots == 0 and reason in result.reasons


@pytest.mark.parametrize('change', [{'price': D('NaN')}, {'drawdown': D('NaN')},
    {'cash': D('Infinity')}, {'cash': D('-1')}, {'stop': D('100')}, {'lot_size': 0}])
def test_invalid_input(proposal, change):
    assert not evaluate_buy(replace(proposal, **change), Settings()).approved


def test_company_exposure_is_aggregated(proposal):
    result = evaluate_buy(replace(proposal, company_exposure=D('14900')), Settings())
    assert not result.approved
