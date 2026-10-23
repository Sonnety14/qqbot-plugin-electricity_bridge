"""Daily electricity check for one explicitly configured QQ account."""
import asyncio,contextlib,hashlib,json,sqlite3,time,os
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
import httpx
from astrbot.api import logger,AstrBotConfig
from astrbot.api.star import Star,StarTools,register,Context
from astrbot.api.event import filter
from .provider import fetch_balance,SessionExpired,WrongMeter

CHINA=timezone(timedelta(hours=8))

@register('astrbot_plugin_electricity','Electricity Bridge contributors','每日电费查询与低余额提醒','0.2.0')
class Electricity(Star):
    def __init__(self,context: Context,config: AstrBotConfig):
        super().__init__(context);self.config=config;self.task=None;self.client=None
        self.folder=StarTools.get_data_dir('astrbot_plugin_electricity')
        self.db=sqlite3.connect(self.folder/'checks.sqlite3')
        self.db.row_factory=sqlite3.Row
        self.db.executescript('CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT NOT NULL);CREATE TABLE IF NOT EXISTS checks(day TEXT PRIMARY KEY,attempts INTEGER NOT NULL,attempted REAL NOT NULL,status TEXT NOT NULL,snapshot TEXT,notice TEXT);')
        self.lock=asyncio.Lock();self.manual_at=0
        self.bridge=None;self.last_health=0
    async def initialize(self):
        self.client=httpx.AsyncClient(timeout=20,trust_env=False)
        # Optional website bridge is configured explicitly; no dependency on another plugin.
        if self.config.get('bridge_enabled',False):
            from .configuration import bridge_settings
            origin,headers=bridge_settings(self.config)
            self.bridge=httpx.AsyncClient(base_url=origin,headers=headers,timeout=30,trust_env=False)
        self.task=asyncio.create_task(self.run())
    def renewal_hint(self):
        from urllib.parse import urlsplit
        url=self.config.get('account_url','')
        u=urlsplit(url)
        return '\n'+url if u.scheme=='https' and u.hostname and not u.username else ''
    async def bridge_api(self,path,data=None):
        r=await self.bridge.post('/comments/bridge/campus/electric/'+path,json=data or {})
        r.raise_for_status();return r.json()
    async def binding_tick(self):
        if not self.bridge:return
        item=(await self.bridge_api('work'))['item']
        if item:
            result={'id':item['id'],'lease':item['lease'],'state':'failed'}
            if item['qq']==str(self.config.get('qq','')):
                try:
                    async with self.lock:
                        snapshot=await fetch_balance(self.client,item['credentials'])
                        updated=datetime.fromisoformat(snapshot['updated']).replace(tzinfo=CHINA)
                        now=datetime.now(CHINA)
                        if now-updated>timedelta(hours=48) or updated>now+timedelta(minutes=10):raise ValueError('stale')
                        if item['action']=='install':
                            credential={**item['credentials'],'binding_version':item['id']}
                            path=self.folder/'credentials.json';temp=self.folder/'credentials.pending'
                            # Atomic file replacement; valid old credentials survive validation failure.
                            fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
                            with os.fdopen(fd,'w',encoding='utf8') as f:
                                json.dump(credential,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
                            os.replace(temp,path);os.chmod(path,0o600)
                            self.credentials();self.set_state('suspended','')
                            day=now.date().isoformat()
                            with self.db:
                                self.db.execute("INSERT INTO checks VALUES (?,1,?,'ok',?,NULL) ON CONFLICT(day) DO UPDATE SET status='ok',snapshot=excluded.snapshot,attempted=excluded.attempted",(day,time.time(),json.dumps(snapshot,ensure_ascii=False)))
                        result.update(state='done' if item['action']=='install' else 'ready',snapshot=snapshot)
                except Exception as exc:logger.warning('Electricity binding: %s',type(exc).__name__)
            await self.bridge_api('result',result)
        if time.time()-self.last_health>60 and (self.folder/'credentials.json').exists():
            credential=self.credentials()
            if credential.get('binding_version'):
                await self.bridge_api('health',{'version':credential['binding_version'],'state':self.state('suspended') or 'active'})
            self.last_health=time.time()
    def state(self,key):
        row=self.db.execute('SELECT value FROM state WHERE key=?',(key,)).fetchone();return row[0] if row else ''
    def set_state(self,key,value):
        with self.db:self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',(key,value))
    def credentials(self):
        raw=(self.folder/'credentials.json').read_bytes()
        fingerprint=hashlib.sha256(raw).hexdigest()
        if fingerprint!=self.state('credential_hash'):
            self.set_state('credential_hash',fingerprint);self.set_state('suspended','')
        return json.loads(raw)
    async def send(self,text):
        platform=self.context.get_platform_inst(self.config.get('platform_id',''))
        if not platform or not getattr(platform,'bot',None):raise RuntimeError('QQ unavailable')
        result=await asyncio.wait_for(platform.bot.call_action('send_private_msg',user_id=int(self.config['qq']),message=[{'type':'text','data':{'text':text}}]),20)
        if not isinstance(result,dict) or result.get('message_id') is None:raise RuntimeError('send not confirmed')
    async def notice(self,day,text):
        # Reserve before the send. A timeout must not produce repeated QQ messages.
        with self.db:
            changed=self.db.execute("UPDATE checks SET notice='sending' WHERE day=? AND notice IS NULL",(day,)).rowcount
        if not changed:return
        try:await self.send(text);status='sent'
        except Exception:status='unknown'
        with self.db:self.db.execute('UPDATE checks SET notice=? WHERE day=?',(status,day))
    async def check(self,now):
        if not self.config.get('enabled',False) or not (self.folder/'credentials.json').exists():return
        now=now.astimezone(CHINA)
        if now.hour<int(self.config.get('hour',9)):return
        day=now.date().isoformat()
        async with self.lock:
            credentials=self.credentials()
            if self.state('suspended'):return
            row=self.db.execute('SELECT * FROM checks WHERE day=?',(day,)).fetchone()
            if row and (row['status'] in ('ok','auth','meter','stale') or row['attempts']>=3 or time.time()-row['attempted']<300):return
            with self.db:self.db.execute("INSERT INTO checks VALUES (?,1,?,'checking',NULL,NULL) ON CONFLICT(day) DO UPDATE SET attempts=attempts+1,attempted=excluded.attempted,status='checking'",(day,time.time()))
            try:
                result=await fetch_balance(self.client,credentials)
                updated=datetime.fromisoformat(result['updated']).replace(tzinfo=CHINA)
                stale=(now-updated)>timedelta(hours=48) or updated>now+timedelta(minutes=10)
                with self.db:self.db.execute('UPDATE checks SET status=?,snapshot=? WHERE day=?',('stale' if stale else 'ok',json.dumps(result,ensure_ascii=False),day))
                if stale:
                    await self.notice(day,'电费数据未及时更新，请在微信核对。\n数据时间：'+result['updated']);return
                if Decimal(result['total'])<Decimal(str(self.config.get('threshold',20))):
                    await self.notice(day,'电费余额提醒\n剩余：'+result['total']+' 元\n低于 '+str(self.config.get('threshold',20))+' 元，请及时充值。\n数据时间：'+result['updated'])
            except (SessionExpired,WrongMeter) as exc:
                reason='auth' if isinstance(exc,SessionExpired) else 'meter'
                self.set_state('suspended',reason)
                with self.db:self.db.execute('UPDATE checks SET status=? WHERE day=?',(reason,day))
                await self.notice(day,('电费查询授权已失效，请更新授权。' if reason=='auth' else '电费查询的房间发生变化，已暂停查询，请重新确认绑定。')+self.renewal_hint())
            except Exception as exc:
                with self.db:self.db.execute("UPDATE checks SET status='failed' WHERE day=?",(day,))
                row=self.db.execute('SELECT attempts FROM checks WHERE day=?',(day,)).fetchone()
                if row[0]>=3:await self.notice(day,'今天的电费查询暂时失败，请在微信核对余额；明天会自动重试。')
                logger.warning('Electricity check failed: %s',type(exc).__name__)
    async def run(self):
        while True:
            try:await self.binding_tick()
            except Exception as exc:logger.warning('Electricity binding poll: %s',type(exc).__name__)
            try:await self.check(datetime.now(CHINA))
            except Exception as exc:logger.warning('Electricity scheduler: %s',type(exc).__name__)
            await asyncio.sleep(5)
    @filter.event_message_type(filter.EventMessageType.ALL,priority=2000)
    async def handle(self,event):
        if event.get_platform_id()!=self.config.get('platform_id','') or not event.is_private_chat() or str(event.get_sender_id())!=str(self.config.get('qq','')):return
        if event.message_str.strip() not in ('电费查询','电费状态'):return
        event.stop_event()
        row=self.db.execute('SELECT * FROM checks ORDER BY day DESC LIMIT 1').fetchone()
        if self.state('suspended'):answer='电费查询已暂停，请更新授权并确认房间。'+self.renewal_hint()
        elif row and row['snapshot']:
            d=json.loads(row['snapshot']);answer='电费余额：'+d['total']+' 元\n数据时间：'+d['updated']+'\n查询日期：'+row['day']+'\n每天 '+str(self.config.get('hour',9)).zfill(2)+':00 查询；低于 '+str(self.config.get('threshold',20))+' 元提醒。'
            if row['status']!='ok':answer+='\n最近查询未成功或数据已过时，请在微信核对。'
        else:answer='尚无有效电费查询记录。'
        await event.send(event.plain_result(answer))
    async def terminate(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):await self.task
        if self.client:await self.client.aclose()
        if self.bridge:await self.bridge.aclose()
        self.db.close()
