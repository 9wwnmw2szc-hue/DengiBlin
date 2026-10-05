from enum import StrEnum


class OrderState(StrEnum):
    CREATED = "CREATED"
    RISK_APPROVED = "RISK_APPROVED"
    SENDING = "SENDING"
    SENT = "SENT"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


TRANSITIONS = {
    OrderState.CREATED: {OrderState.RISK_APPROVED, OrderState.REJECTED},
    OrderState.RISK_APPROVED: {OrderState.SENDING, OrderState.CANCELLED},
    OrderState.SENDING: {OrderState.SENT, OrderState.FILLED, OrderState.PARTIALLY_FILLED,
                         OrderState.REJECTED, OrderState.UNKNOWN},
    OrderState.SENT: {OrderState.PARTIALLY_FILLED, OrderState.FILLED,
                     OrderState.CANCEL_REQUESTED, OrderState.REJECTED, OrderState.UNKNOWN},
    OrderState.PARTIALLY_FILLED: {OrderState.FILLED, OrderState.CANCEL_REQUESTED, OrderState.UNKNOWN},
    OrderState.CANCEL_REQUESTED: {OrderState.CANCELLED, OrderState.FILLED,
                                OrderState.PARTIALLY_FILLED, OrderState.UNKNOWN},
    OrderState.UNKNOWN: set(),
}


def transition(current: OrderState, target: OrderState) -> OrderState:
    if target not in TRANSITIONS.get(current, set()):
        raise ValueError(f"Forbidden order transition: {current} -> {target}")
    return target


def reconcile_unknown(current: OrderState, broker_state: OrderState) -> OrderState:
    if current != OrderState.UNKNOWN or broker_state not in {
        OrderState.SENT, OrderState.PARTIALLY_FILLED, OrderState.FILLED,
        OrderState.CANCELLED, OrderState.REJECTED,
    }:
        raise ValueError("Authoritative broker reconciliation required")
    return broker_state
