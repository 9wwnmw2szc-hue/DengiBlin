from datetime import datetime, timedelta, timezone
from decimal import Decimal
import httpx
import pytest
from app.brokers.tinvest import TInvestSandboxReader, BrokerError, number, timestamp


def test_fixed_sandbox_host_and_read_allowlist():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'accounts':[]})
    with TInvestSandboxReader('fixture-token-only', httpx.MockTransport(handler)) as broker:
        assert broker.accounts() == []
        with pytest.raises(BrokerError, match='METHOD_NOT_ALLOWED'):
            broker._call('OrdersService','PostOrder',{})
        with pytest.raises(BrokerError, match='METHOD_NOT_ALLOWED'):
            broker._call('SandboxService','PostSandboxOrder',{})
    assert len(requests) == 1
    assert requests[0].url.host == 'sandbox-invest-public-api.tbank.ru'
    assert requests[0].headers['Authorization'] == 'Bearer fixture-token-only'


@pytest.mark.parametrize('status,code',[(401,'TOKEN_REJECTED'),(403,'TOKEN_REJECTED'),(429,'RATE_LIMIT'),(500,'BROKER_ERROR'),(302,'BROKER_ERROR')])
def test_errors_do_not_echo_upstream_secrets(status, code):
    with TInvestSandboxReader('fixture-token-only', httpx.MockTransport(lambda r: httpx.Response(status, text='fixture-token-only'))) as broker:
        with pytest.raises(BrokerError) as error:
            broker.accounts()
        assert str(error.value) == code


def test_nanosecond_quotations_are_exact():
    assert number({'units':'100','nano':1}) == Decimal('100.000000001')
    assert number({'units':'-1','nano':-500000000}) == Decimal('-1.5')
    assert number({'nano':500000000}) == Decimal('0.5')
    assert number({}) == Decimal('0')
    for value in ({'units':'NaN'},{'units':'1','nano':-1},{'units':'0','nano':1000000000}, {'units':1.9}, {'units':True}, {'units':2**63}):
        with pytest.raises(BrokerError):
            number(value)


def test_price_and_timestamp_validation():
    response = {'lastPrices':[{'instrumentUid':'test-uid', 'price':{'units':'100','nano':1}, 'time':'2026-10-05T10:00:00Z'}]}
    with TInvestSandboxReader('fixture-token-only',httpx.MockTransport(lambda r: httpx.Response(200,json=response))) as broker:
        price = broker.prices(['test-uid'])[0]
        assert price['price'] == '100.000000001' and price['at'].tzinfo is not None
        with pytest.raises(BrokerError):
            broker.prices(['different-uid'])
    with pytest.raises(BrokerError):
        timestamp('2026-10-05T10:00:00')


def test_ohlcv_validation_and_complete_flag():
    now = datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    q = lambda n: {'units':str(n),'nano':0}
    candle = {'open':q(100),'high':q(105),'low':q(99),'close':q(101),
              'volume':'123', 'time':now.isoformat(),'isComplete':True}
    with TInvestSandboxReader('fixture-token-only',httpx.MockTransport(lambda r: httpx.Response(200,json={'candles':[candle]}))) as broker:
        result = broker.candles('test-uid',now-timedelta(hours=1),now+timedelta(hours=1))[0]
        assert result['volume'] == 123 and result['complete']
        candle['low'] = q(102)
        with pytest.raises(BrokerError):
            broker.candles('test-uid',now-timedelta(hours=1),now+timedelta(hours=1))


def test_malformed_repeated_field():
    with TInvestSandboxReader('fixture-token-only',httpx.MockTransport(lambda r: httpx.Response(200,json={'accounts':'wrong'}))) as broker:
        with pytest.raises(BrokerError,match='MALFORMED_RESPONSE'):
            broker.accounts()
