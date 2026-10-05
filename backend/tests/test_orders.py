import pytest
from app.order_states import OrderState as S, transition, reconcile_unknown


def test_submission_requires_risk_approval():
    with pytest.raises(ValueError):
        transition(S.CREATED, S.SENDING)
    assert transition(transition(S.CREATED, S.RISK_APPROVED), S.SENDING) == S.SENDING


def test_unknown_blocks_retry():
    assert transition(S.SENDING, S.UNKNOWN) == S.UNKNOWN
    with pytest.raises(ValueError):
        transition(S.UNKNOWN, S.SENDING)
    assert reconcile_unknown(S.UNKNOWN, S.FILLED) == S.FILLED


def test_terminal_cannot_be_reopened():
    for state in (S.FILLED, S.CANCELLED, S.REJECTED, S.FAILED):
        with pytest.raises(ValueError):
            transition(state, S.SENDING)
