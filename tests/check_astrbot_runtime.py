"""Run in AstrBot with temporary data and an HTTP mock; no real QQ or electricity requests."""
import sys,asyncio,tempfile,json,importlib,types
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'plugin'))
from astrbot_plugin_electricity.main import Electricity,CHINA
from astrbot_plugin_electricity.provider import parse_balance,SessionExpired,WrongMeter

def page(amount='19.00',room='fixture-room',updated='2026-10-23 07:00:00'):
 return f'<span id="roomaddr">{room}</span><span>预付费余额：</span><span>{amount} 元</span><span>补助电余额：</span><span>0.00 元</span><span>总余额：</span><span>{amount} 元</span><div>数据更新时间：{updated}</div>'

async def main():
 now=datetime(2026,10,23,9,tzinfo=CHINA)
 for case in ['low','equal','auth','room','stale','network','send_timeout']:
  with tempfile.TemporaryDirectory() as td:
   folder=Path(td);(folder/'credentials.json').write_text(json.dumps({'cookie':'fixture=only','room':'fixture-room'}))
   sends=[];requests=[]
   async def send(action,**kwargs):
    assert action=='send_private_msg' and kwargs['user_id']==1234567890
    sends.append(kwargs)
    if case=='send_timeout':raise TimeoutError()
    return {'message_id':1}
   def transport(req):
    requests.append(req);assert req.method=='GET' and str(req.url)=='http://wx.cdzht.com/meter_main'
    if case=='network':raise httpx.ConnectError('fixture')
    if case=='auth':return httpx.Response(302,headers={'Location':'https://open.weixin.qq.com/'})
    body=page('20.00' if case=='equal' else '19.00',room='other' if case=='room' else 'fixture-room',updated='2026-10-19 07:00:00' if case=='stale' else '2026-10-23 07:00:00')
    return httpx.Response(200,text=body)
   ctx=types.SimpleNamespace(get_platform_inst=lambda _:types.SimpleNamespace(bot=types.SimpleNamespace(call_action=send)))
   with patch('astrbot_plugin_electricity.main.StarTools.get_data_dir',return_value=folder):
    obj=Electricity(ctx,{'enabled':True,'qq':'1234567890','threshold':20,'hour':9})
   obj.client=httpx.AsyncClient(transport=httpx.MockTransport(transport))
   await obj.check(now.replace(hour=8));assert not requests
   await obj.check(now);await obj.check(now)
   if case=='network':
    for _ in range(2):
     obj.db.execute('UPDATE checks SET attempted=0');obj.db.commit();await obj.check(now)
    assert len(requests)==3 and len(sends)==1
   else:
    assert len(requests)==1 and len(sends)==(0 if case=='equal' else 1)
   if case in ('room','auth'):assert obj.state('suspended')
   if case=='send_timeout':assert obj.db.execute('SELECT notice FROM checks').fetchone()[0]=='unknown'
   if case=='stale':assert '未及时更新' in sends[0]['message'][0]['data']['text']
   await obj.terminate()
 with tempfile.TemporaryDirectory() as td:
  folder=Path(td);old={'cookie':'old-fixture','room':'fixture-room'}
  (folder/'credentials.json').write_text(json.dumps(old))
  ctx=types.SimpleNamespace(get_platform_inst=lambda _:None)
  with patch('astrbot_plugin_electricity.main.StarTools.get_data_dir',return_value=folder):obj=Electricity(ctx,{'enabled':True,'qq':'1234567890','threshold':20,'hour':9})
  now=datetime.now(CHINA);updated=now.strftime('%Y-%m-%d %H:%M:%S');responses=[]
  obj.client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,text=page('25.84',updated=updated))))
  item={'id':'fixture-version-1','lease':'fixture-lease','action':'validate','qq':'1234567890','credentials':{'cookie':'new-fixture','room':'fixture-room'}}
  async def api(path,data=None):
   if path=='work':return {'item':item}
   responses.append((path,data));return {'ok':True}
  obj.bridge=types.SimpleNamespace();obj.bridge_api=api;obj.last_health=__import__('time').time()
  await obj.binding_tick()
  assert responses[-1][1]['state']=='ready' and json.loads((folder/'credentials.json').read_text())==old
  obj.set_state('suspended','auth');item['action']='install'
  await obj.binding_tick()
  assert responses[-1][1]['state']=='done' and not obj.state('suspended')
  saved=(folder/'credentials.json').read_bytes();assert json.loads(saved)['binding_version']==item['id']
  obj.set_state('suspended','auth');item['credentials']['room']='other-room'
  await obj.binding_tick()
  assert responses[-1][1]['state']=='failed' and (folder/'credentials.json').read_bytes()==saved and obj.state('suspended')=='auth'
  obj.bridge=None;await obj.terminate()
 print('PASS daily clock, threshold, dedup, failures, staged binding, atomic renewal, failed renewal preserves old credentials')
asyncio.run(main())
