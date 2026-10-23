"""No sockets, capture processes, production accounts or real credentials."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

provider=load('electric_provider','plugin/astrbot_plugin_electricity/provider.py')
config=load('plugin_config','plugin/astrbot_plugin_electricity/configuration.py')
assistant_config=load('assistant_config','assistant/configuration.py')
HTML='<span id="roomaddr">fixture-room</span>预付费余额：19.00 元 补助电余额：0.00 元 总余额：19.00 元 数据更新时间：2026-01-01 09:00:00'

def test_parser_and_room_protection():
    assert provider.parse_balance(HTML,'fixture-room')['total']=='19.00'
    with pytest.raises(provider.WrongMeter):provider.parse_balance(HTML,'other-room')
    with pytest.raises(provider.SessionExpired):provider.parse_balance('<html>login</html>','fixture-room')

def test_read_only_fetch_does_not_follow_auth():
    requests=[]
    def respond(req):
        requests.append(req)
        assert req.method=='GET' and str(req.url)=='http://wx.cdzht.com/meter_main'
        assert req.headers['cookie']=='fixture-only'
        return httpx.Response(302,headers={'location':'https://example.invalid/login'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(provider.SessionExpired):await provider.fetch_balance(client,{'cookie':'fixture-only','room':'fixture-room'})
    asyncio.run(run());assert len(requests)==1

@pytest.mark.parametrize('origin',['http://8.8.8.8','http://0.0.0.0','http://localhost','http://127.0.0.1/path','https://127.0.0.1'])
def test_bridge_rejects_invalid_destination(origin):
    with pytest.raises(ValueError):config.bridge_settings({'backend_origin':origin,'backend_host':'test.example','bridge_token':'x'*64})

def test_bridge_explicit_configuration():
    origin,headers=config.bridge_settings({'backend_origin':'http://127.0.0.1:8090','backend_host':'test.example','bridge_token':'x'*64})
    assert origin=='http://127.0.0.1:8090' and headers['Host']=='test.example'

@pytest.mark.parametrize('origin',['http://test.example','https://example.invalid','https://u:p@test.example','https://test.example/path','https://test.example?redirect=bad'])
def test_assistant_rejects_untrusted_config(tmp_path,origin):
    p=tmp_path/'config.json';p.write_text(json.dumps({'website_origin':origin}))
    with pytest.raises(ValueError):assistant_config.load_upload_url(p)

def test_assistant_fixed_upload_route(tmp_path):
    p=tmp_path/'config.json';p.write_text(json.dumps({'website_origin':'https://test.example'}))
    assert assistant_config.load_upload_url(p)=='https://test.example/tools/campus/electric/upload'

def test_assistant_saves_only_origin_and_rejects_invalid_change(tmp_path):
    path=tmp_path/'config.json'
    assistant_config.save_origin(' https://test.example/ ',path)
    assert json.loads(path.read_text())=={'website_origin':'https://test.example'}
    before=path.read_bytes()
    for bad in ['http://test.example','https://test.example:bad','https://test.example/account/']:
        with pytest.raises(ValueError):assistant_config.save_origin(bad,path)
    assert path.read_bytes()==before

def test_independent_router_full_staging_and_renewal(tmp_path):
    import hashlib,hmac
    from integration.router import build_electric_router
    dbpath=tmp_path/'test.sqlite3'
    with sqlite3.connect(dbpath) as db:
        db.executescript("""CREATE TABLE users(id INTEGER PRIMARY KEY,auth_version INTEGER,status TEXT);
        CREATE TABLE email_credentials(user_id INTEGER,verified_at REAL);
        CREATE TABLE campus_qq_bindings(user_id INTEGER,qq TEXT);
        INSERT INTO users VALUES(1,1,'active'); INSERT INTO email_credentials VALUES(1,1);
        INSERT INTO campus_qq_bindings VALUES(1,'1234567890');""")
    identity=SimpleNamespace(db=str(dbpath),load_session=lambda cookie: {'id':1,'verified_at':1,'csrf':'fixture-csrf','user_auth_version':1} if cookie=='fixture-session' else None)
    app=FastAPI();app.include_router(build_electric_router(identity,'https://test.example',SimpleNamespace(limit=lambda *args:True),'x'*48,'1234567890'))
    client=TestClient(app,base_url='https://test.example')
    p='/tools/campus/electric/';b='/comments/bridge/campus/electric/'
    assert client.get(p+'status').status_code==401
    client.cookies.set('__Host-site_session','fixture-session')
    headers={'Origin':'https://test.example','X-CSRF-Token':'fixture-csrf'}
    internal={'Authorization':'Bearer '+hmac.new(b'x'*48,b'campus-bindings-v1',hashlib.sha256).hexdigest()}
    credentials={'cookie':'connect.sid=fixture-session-only','user_agent':'fixture-UA','room':'fixture-room'}
    snapshot=provider.parse_balance(HTML,'fixture-room')
    for _ in range(2):
        assert client.post(p+'start').status_code==403
        token=client.post(p+'start',headers=headers).json()['code'][9:]
        bearer={'Authorization':'Bearer '+token}
        assert client.post(p+'upload',headers=bearer,json=credentials).status_code==200
        assert client.post(p+'upload',headers=bearer,json=credentials).status_code==401
        with sqlite3.connect(dbpath) as db:assert credentials['cookie'] not in db.execute('SELECT payload FROM electric_jobs').fetchone()[0]
        work=client.post(b+'work',headers=internal).json()['item'];assert work['action']=='validate'
        result={'id':work['id'],'lease':work['lease'],'state':'ready','snapshot':snapshot}
        assert client.post(b+'result',headers=internal,json=result).status_code==200
        assert 'cookie' not in client.get(p+'status').text
        assert client.post(p+'confirm',headers=headers,json={'id':work['id']}).status_code==200
        install=client.post(b+'work',headers=internal).json()['item'];assert install['action']=='install'
        assert client.post(b+'result',headers=internal,json={**result,'lease':install['lease'],'state':'done'}).status_code==200
        assert client.get(p+'status').json()['binding']['state']=='active'
        assert client.post(b+'health',headers=internal,json={'version':work['id'],'state':'auth'}).status_code==200
    with sqlite3.connect(dbpath) as db:assert db.execute('SELECT payload FROM electric_jobs').fetchone()[0] is None

def test_plugin_package_whitelist(tmp_path,monkeypatch):
    pack=load('pack_plugin','scripts/package_plugin.py')
    import zipfile
    # Redirect output by staging just the explicit source files into a fixture tree.
    dest=tmp_path/'plugin/astrbot_plugin_electricity';dest.mkdir(parents=True)
    for name in pack.FILES:(dest/name).write_bytes((ROOT/'plugin/astrbot_plugin_electricity'/name).read_bytes())
    (dest/'credentials.json').write_text('DO_NOT_PACKAGE')
    monkeypatch.setattr(pack,'ROOT',tmp_path);pack.main()
    with zipfile.ZipFile(tmp_path/'dist/astrbot_plugin_electricity.zip') as z:
        assert len(z.namelist())==len(pack.FILES)
        assert not any('credentials' in x for x in z.namelist())
