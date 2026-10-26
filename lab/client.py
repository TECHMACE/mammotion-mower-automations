"""Local-only lab API client; refuses any URL except its hardcoded loopback lab."""
import json
import os
from pathlib import Path
import secrets
import urllib.request
import urllib.parse

BASE = "http://127.0.0.1:18123"
PRIVATE = Path(__file__).parent / ".evidence"
AUTH = PRIVATE / "auth.json"

def api(path, data=None, token=None, form=False, method=None):
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("Only relative paths on the isolated lab are allowed")
    headers = {}
    if token: headers["Authorization"] = "Bearer " + token
    body = None
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    req = urllib.request.Request(BASE+path,body,headers,method=method)
    with urllib.request.urlopen(req,timeout=30) as response:
        content = response.read()
        return json.loads(content) if content else {}

def login():
    PRIVATE.mkdir(exist_ok=True)
    if AUTH.exists():
        saved=json.loads(AUTH.read_text())
        tokens=api('/auth/token',dict(grant_type='refresh_token',refresh_token=saved['refresh_token'],client_id=BASE+'/'),form=True)
        return tokens['access_token']
    password=secrets.token_urlsafe(24)
    result=api('/api/onboarding/users',dict(name='Mower Lab Tester',username='mower_lab',password=password,client_id=BASE+'/',language='en'))
    tokens=api('/auth/token',dict(grant_type='authorization_code',code=result['auth_code'],client_id=BASE+'/'),form=True)
    saved={**tokens,'username':'mower_lab','password':password}
    AUTH.write_text(json.dumps(saved));os.chmod(AUTH,0o600)
    return tokens['access_token']

if __name__ == '__main__':
    token=login()
    states=api('/api/states',token=token)
    print(json.dumps({'lab':BASE,'entities':sorted(x['entity_id'] for x in states if 'lab_' in x['entity_id'])},indent=2))
