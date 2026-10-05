"""Sandbox-only REST reads. Host and method allowlist are not user configurable."""
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import httpx

SANDBOX_URL = 'https://sandbox-invest-public-api.tbank.ru/rest/'
PREFIX = 'tinkoff.public.invest.api.contract.v1.'
READ_METHODS = frozenset({
    ('SandboxService', 'GetSandboxAccounts'), ('SandboxService', 'GetSandboxPortfolio'),
    ('SandboxService', 'GetSandboxPositions'), ('SandboxService', 'GetSandboxOrders'),
    ('InstrumentsService', 'Shares'), ('MarketDataService', 'GetLastPrices'),
    ('MarketDataService', 'GetCandles'), ('MarketDataService', 'GetTradingStatus'),
})


class BrokerError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def integer(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise BrokerError('MALFORMED_RESPONSE')
    if isinstance(value, str) and not re.fullmatch(r'-?[0-9]{1,19}', value):
        raise BrokerError('MALFORMED_RESPONSE')
    result = int(value)
    if not -(2**63) <= result < 2**63:
        raise BrokerError('MALFORMED_RESPONSE')
    return result


def number(value: dict) -> Decimal:
    try:
        if not isinstance(value, dict):
            raise ValueError()
        # Protobuf JSON can omit scalar fields whose value is zero.
        units = integer(value.get('units', 0))
        nano = integer(value.get('nano', 0))
        if abs(nano) >= 1_000_000_000 or (units > 0 and nano < 0) or (units < 0 and nano > 0):
            raise ValueError()
        return Decimal(units) + Decimal(nano) / Decimal(1_000_000_000)
    except (KeyError, ValueError, TypeError, InvalidOperation):
        raise BrokerError('MALFORMED_RESPONSE') from None


def timestamp(value: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError()
        return stamp.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise BrokerError('MALFORMED_RESPONSE') from None


def items(response: dict, field: str) -> list[dict]:
    value = response.get(field, [])  # protobuf omits an empty repeated field
    if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
        raise BrokerError('MALFORMED_RESPONSE')
    return value


class TInvestSandboxReader:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(base_url=SANDBOX_URL, headers={'Authorization': f'Bearer {token}', 'x-app-name': 'MarketBrain'}, timeout=httpx.Timeout(8, connect=5), follow_redirects=False, transport=transport)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.client.close()

    def _call(self, service: str, method: str, body: dict) -> dict:
        if (service, method) not in READ_METHODS:
            raise BrokerError('METHOD_NOT_ALLOWED')
        try:
            response = self.client.post(f'{PREFIX}{service}/{method}', json=body)
        except httpx.HTTPError:
            raise BrokerError('BROKER_UNAVAILABLE') from None
        if response.status_code in (401, 403):
            raise BrokerError('TOKEN_REJECTED')
        if response.status_code == 429:
            raise BrokerError('RATE_LIMIT')
        if response.status_code != 200:
            raise BrokerError('BROKER_ERROR')
        if len(response.content) > 8_000_000:
            raise BrokerError('RESPONSE_TOO_LARGE')
        try:
            payload = response.json()
            if not isinstance(payload, dict) or 'code' in payload:
                raise ValueError()
            return payload
        except (ValueError, json.JSONDecodeError):
            raise BrokerError('MALFORMED_RESPONSE') from None

    def accounts(self):
        accounts = items(self._call('SandboxService', 'GetSandboxAccounts', {}), 'accounts')
        result = []
        for account in accounts:
            if not account.get('id') or not isinstance(account['id'], str):
                raise BrokerError('MALFORMED_RESPONSE')
            result.append({'id': account['id'], 'name': str(account.get('name', 'Sandbox')),
                           'status': str(account.get('status', 'UNKNOWN')),
                           'access': str(account.get('accessLevel', 'UNKNOWN'))})
        return result

    def instruments(self):
        response = self._call('InstrumentsService', 'Shares', {'instrumentStatus': 'INSTRUMENT_STATUS_BASE'})
        result = []
        for instrument in items(response, 'instruments'):
            if instrument.get('classCode') != 'TQBR' or instrument.get('currency') != 'rub' or instrument.get('apiTradeAvailableFlag') is not True:
                continue
            try:
                lot = integer(instrument['lot'])
                if lot < 1 or not instrument['uid'] or not instrument['ticker']:
                    raise ValueError()
                result.append({'uid': instrument['uid'], 'figi': instrument.get('figi', ''),
                    'ticker': instrument['ticker'], 'name': instrument.get('name', instrument['ticker']),
                    'lot': lot, 'currency': 'rub', 'exchange': instrument.get('exchange', ''),
                    'class_code': 'TQBR', 'tradable': True})
            except (ValueError, TypeError, KeyError):
                raise BrokerError('MALFORMED_RESPONSE') from None
        return result

    def prices(self, instrument_ids):
        response = self._call('MarketDataService', 'GetLastPrices', {'instrumentId': instrument_ids})
        result = []
        for price in items(response, 'lastPrices'):
            amount = number(price.get('price', {}))
            uid = price.get('instrumentUid')
            stamp = timestamp(price.get('time'))
            if not uid or uid not in instrument_ids or amount <= 0:
                raise BrokerError('MALFORMED_RESPONSE')
            result.append({'uid': uid, 'price': str(amount), 'at': stamp})
        return result

    def candles(self, instrument_id, start, end):
        response = self._call('MarketDataService', 'GetCandles', {'instrumentId': instrument_id,
            'from': start.isoformat(), 'to': end.isoformat(), 'interval': 'CANDLE_INTERVAL_HOUR'})
        result = []
        for candle in items(response, 'candles'):
            try:
                prices = {field: number(candle.get(field, {})) for field in ('open', 'high', 'low', 'close')}
                volume = integer(candle.get('volume', 0))
                stamp = timestamp(candle.get('time'))
                if min(prices.values()) <= 0 or volume < 0 or prices['low'] > min(prices['open'], prices['close']) or prices['high'] < max(prices['open'], prices['close']) or not start <= stamp <= end:
                    raise ValueError()
                result.append({'at': stamp, **{k: str(v) for k, v in prices.items()},
                               'volume': volume, 'complete': candle.get('isComplete') is True})
            except (ValueError, TypeError):
                raise BrokerError('MALFORMED_RESPONSE') from None
        return result

    def trading_status(self, instrument_id):
        response = self._call('MarketDataService', 'GetTradingStatus', {'instrumentId': instrument_id})
        if response.get('instrumentUid') != instrument_id:
            raise BrokerError('MALFORMED_RESPONSE')
        return {'status': str(response.get('tradingStatus', 'UNKNOWN')),
                'api_available': response.get('apiTradeAvailableFlag') is True,
                'market_orders': response.get('marketOrderAvailableFlag') is True}

    def portfolio(self, account_id):
        response = self._call('SandboxService', 'GetSandboxPortfolio', {'accountId': account_id, 'currency': 'RUB'})
        if response.get('accountId') != account_id:
            raise BrokerError('MALFORMED_RESPONSE')
        total = response.get('totalAmountPortfolio')
        positions = []
        for position in items(response, 'positions'):
            positions.append({'uid': position.get('instrumentUid', ''), 'figi': position.get('figi', ''),
                'type': position.get('instrumentType', ''), 'quantity': str(number(position.get('quantity', {}))),
                'price': str(number(position.get('currentPrice', {}))),
                'currency': position.get('currentPrice', {}).get('currency', '')})
        return {'account_id': account_id, 'equity': str(number(total)) if total else None,
                'currency': total.get('currency') if total else None, 'positions': positions}

    def positions(self, account_id):
        response = self._call('SandboxService', 'GetSandboxPositions', {'accountId': account_id})
        if response.get('limitsLoadingInProgress') is True:
            raise BrokerError('PORTFOLIO_NOT_READY')
        def money_list(field):
            return [{'currency': m.get('currency'), 'amount': str(number(m))} for m in items(response, field)]
        return {'money': money_list('money'), 'blocked': money_list('blocked')}

    def orders(self, account_id):
        response = self._call('SandboxService', 'GetSandboxOrders', {'accountId': account_id})
        result = []
        for order in items(response, 'orders'):
            try:
                requested, executed = integer(order.get('lotsRequested', 0)), integer(order.get('lotsExecuted', 0))
                if requested < 0 or not 0 <= executed <= requested or not order.get('orderId'):
                    raise ValueError()
                result.append({'id': order['orderId'], 'uid': order.get('instrumentUid', ''),
                    'state': order.get('executionReportStatus', 'UNKNOWN'),
                    'direction': order.get('direction', 'UNKNOWN'), 'lots': requested, 'filled_lots': executed})
            except (ValueError, TypeError):
                raise BrokerError('MALFORMED_RESPONSE') from None
        return result
