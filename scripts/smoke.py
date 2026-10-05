"""Local CI smoke against real Compose services. No broker tokens or market fixtures."""
import json
import secrets
from decimal import Decimal
from http.cookiejar import CookieJar
from urllib.request import build_opener, HTTPCookieProcessor, Request
from urllib.error import HTTPError

BASE = 'http://localhost:3000'
opener = build_opener(HTTPCookieProcessor(CookieJar()))


def request(path, body=None, expected=200, origin=BASE):
    headers = {'Origin':origin}
    payload = None
    if body is not None:
        payload=json.dumps(body).encode()
        headers['Content-Type']='application/json'
    req=Request(BASE+'/api/'+path,data=payload,headers=headers)
    try:
        response=opener.open(req,timeout=15)
    except HTTPError as error:
        response=error
    assert response.status == expected, f'{path}: expected {expected}, got {response.status}'
    return json.loads(response.read())


credentials={'email':'ci-'+secrets.token_hex(8)+'@localhost.invalid','password':secrets.token_urlsafe(32)}
request('auth/register',credentials,201)
dashboard=request('dashboard')
assert Decimal(dashboard['portfolio']['cash']) == 1000
assert dashboard['safe_mode'] and dashboard['autopilot'] == 'STOPPED'
assert request('broker')['status'] == 'NOT_CONNECTED'
assert request('market')['instruments'] == []
request('sandbox/balance',{'amount':'1200.01'})
assert Decimal(request('dashboard')['portfolio']['cash']) == Decimal('1200.01')
request('sandbox/balance',{'amount':'9999'},403,'https://untrusted.invalid')
request('autopilot/start',{},409)
request('real/activate',{},403)
assert request('dashboard')['decisions'][0]['action'] == 'SKIP'
request('auth/logout',{})
request('dashboard',expected=401)
request('auth/login',credentials)
assert Decimal(request('dashboard')['portfolio']['cash']) == Decimal('1200.01')
print('Compose smoke passed: auth, persistence, CSRF, Sandbox, safe mode and REAL block.')
