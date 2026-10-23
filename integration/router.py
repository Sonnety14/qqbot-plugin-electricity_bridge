"""Pilot electricity binding: short-lived tickets, encrypted staging, explicit confirmation."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
import sqlite3
from contextlib import contextmanager

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

@contextmanager
def connect(path):
    db=sqlite3.connect(path)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db: yield db
    finally: db.close()

P = '/tools/campus/electric'
B = '/comments/bridge/campus/electric'


def build_electric_router(identity, origin, store, bridge_token, pilot_qq, session_cookie="__Host-site_session"):
    router = APIRouter()
    bridge = hmac.new(bridge_token.encode(), b'campus-bindings-v1', hashlib.sha256).hexdigest()
    cipher = Fernet(base64.urlsafe_b64encode(hmac.new(bridge_token.encode(), b'electric-staging-v1', hashlib.sha256).digest()))
    with connect(identity.db) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS electric_jobs(
          user_id INTEGER PRIMARY KEY REFERENCES users(id), id TEXT UNIQUE NOT NULL, token_hash TEXT NOT NULL,
          auth_version INTEGER NOT NULL, qq TEXT NOT NULL, expires REAL NOT NULL, state TEXT NOT NULL,
          payload TEXT, snapshot TEXT, lease TEXT, lease_until REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS electric_bindings(
          user_id INTEGER PRIMARY KEY REFERENCES users(id), qq TEXT NOT NULL, version TEXT NOT NULL,
          state TEXT NOT NULL, snapshot TEXT NOT NULL, updated REAL NOT NULL);
        ''')

    def clean(db):
        db.execute("UPDATE electric_jobs SET payload=NULL,token_hash='',state='expired' WHERE expires<=? AND state NOT IN ('done','expired')", (time.time(),))

    def session(request, write=False):
        s = identity.load_session(request.cookies.get(session_cookie, ''))
        if not s: raise HTTPException(401, '请先登录')
        if not s.get('verified_at'): raise HTTPException(403, '请先验证邮箱')
        if write and (request.headers.get('origin') != origin or not secrets.compare_digest(request.headers.get('x-csrf-token', ''), s['csrf'])):
            raise HTTPException(403, '请刷新页面重试')
        request.state.user_id = s['id']
        return s

    def allowed(db, uid):
        row = db.execute('SELECT qq FROM campus_qq_bindings WHERE user_id=?', (uid,)).fetchone()
        return bool(row and row['qq'] == pilot_qq)

    def internal(request):
        if not secrets.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + bridge): raise HTTPException(401)

    def valid_job(db, job):
        return job and job['expires'] > time.time() and db.execute('''SELECT 1 FROM users u
          JOIN email_credentials e ON e.user_id=u.id JOIN campus_qq_bindings q ON q.user_id=u.id
          WHERE u.id=? AND u.auth_version=? AND u.status='active' AND e.verified_at IS NOT NULL AND q.qq=?''',
          (job['user_id'], job['auth_version'], job['qq'])).fetchone()

    @router.get(P + '/status')
    def status(request: Request):
        s = session(request)
        with connect(identity.db) as db:
            clean(db)
            enabled = allowed(db, s['id'])
            job = db.execute('SELECT * FROM electric_jobs WHERE user_id=?', (s['id'],)).fetchone()
            binding = db.execute('SELECT state,snapshot,updated FROM electric_bindings WHERE user_id=?', (s['id'],)).fetchone()
            j = {'state':job['state'], 'id':job['id'], 'snapshot':json.loads(job['snapshot']) if job['snapshot'] else None} if valid_job(db, job) else None
        return {'available':enabled, 'job':j, 'binding':dict(binding, snapshot=json.loads(binding['snapshot'])) if binding else None}

    @router.get(P + '/assistant.zip')
    def download(request: Request):
        s = session(request)
        with connect(identity.db) as db:
            if not allowed(db, s['id']): raise HTTPException(403, '暂未开放')
        p = Path(identity.db).parent / 'campus-media' / 'electric-assistant.zip'
        if not p.is_file(): raise HTTPException(503, '助手正在准备')
        return FileResponse(p, filename='Electricity-Assistant.zip', media_type='application/zip')

    @router.post(P + '/start')
    def start(request: Request):
        s = session(request, True)
        if not store.limit('electric-start:' + str(s['id']), 5): raise HTTPException(429, '请稍后重试')
        token = secrets.token_urlsafe(32)
        with connect(identity.db) as db:
            db.execute('BEGIN IMMEDIATE')
            clean(db)
            if not allowed(db, s['id']): raise HTTPException(403, '请先绑定 QQ；电费功能目前试用中')
            old = db.execute('SELECT state FROM electric_jobs WHERE user_id=?', (s['id'],)).fetchone()
            if old and old['state'] in ('queued','processing'): raise HTTPException(409, '正在保存，请稍候')
            db.execute('''INSERT OR REPLACE INTO electric_jobs(user_id,id,token_hash,auth_version,qq,expires,state)
              VALUES(?,?,?,?,?,?,'waiting')''', (s['id'], secrets.token_hex(16), digest(token), s['user_auth_version'], pilot_qq, time.time()+600))
        return {'code':'ELECTRIC-' + token, 'expires_in':600}

    @router.post(P + '/upload')
    async def upload(request: Request):
        # Never reflect a supplied cookie through pydantic validation errors.
        token = request.headers.get('authorization', '').removeprefix('Bearer ')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token): raise HTTPException(401)
        with connect(identity.db) as db:
            job = db.execute('SELECT * FROM electric_jobs WHERE token_hash=?', (digest(token),)).fetchone()
            if not valid_job(db, job) or job['state'] != 'waiting': raise HTTPException(401, '连接码已失效，请重新生成')
        try:
            body = await request.json()
            assert isinstance(body, dict) and set(body) == {'cookie','user_agent','room'}
            assert re.fullmatch(r'connect\.sid=[A-Za-z0-9%._~+:/=-]{10,1024}', body['cookie'])
            assert isinstance(body['user_agent'], str) and 0 < len(body['user_agent']) <= 512 and not any(ord(c)<32 or ord(c)>126 for c in body['user_agent'])
            assert isinstance(body['room'], str) and 0 < len(body['room']) <= 200 and not any(ord(c)<32 for c in body['room'])
        except Exception: raise HTTPException(400, '连接数据无效') from None
        encrypted = cipher.encrypt(json.dumps(body, ensure_ascii=False).encode()).decode()
        with connect(identity.db) as db:
            changed = db.execute("UPDATE electric_jobs SET payload=?,token_hash='',state='validating' WHERE id=? AND state='waiting' AND expires>?", (encrypted,job['id'],time.time())).rowcount
            if not changed: raise HTTPException(409, '连接已处理')
        return {'ok':True}

    @router.post(P + '/confirm')
    async def confirm(request: Request):
        s = session(request, True)
        data = await request.json()
        with connect(identity.db) as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute('SELECT * FROM electric_jobs WHERE user_id=?', (s['id'],)).fetchone()
            if not valid_job(db,job) or job['state'] != 'ready' or data.get('id') != job['id']: raise HTTPException(409, '请重新连接')
            db.execute("UPDATE electric_jobs SET state='queued',lease=NULL,lease_until=0 WHERE id=?", (job['id'],))
        return {'ok':True}

    @router.post(B + '/work')
    def work(request: Request):
        internal(request)
        with connect(identity.db) as db:
            db.execute('BEGIN IMMEDIATE')
            clean(db)
            job = db.execute("SELECT * FROM electric_jobs WHERE state IN ('validating','queued','processing') AND lease_until<? ORDER BY expires LIMIT 1", (time.time(),)).fetchone()
            if not valid_job(db,job): return {'item':None}
            lease = secrets.token_hex(16)
            action = 'validate' if job['state']=='validating' else 'install'
            db.execute('UPDATE electric_jobs SET lease=?,lease_until=? WHERE id=?', (lease,time.time()+60,job['id']))
            return {'item':{'id':job['id'],'lease':lease,'action':action,'qq':job['qq'],'credentials':json.loads(cipher.decrypt(job['payload'].encode()))}}

    @router.post(B + '/result')
    async def result(request: Request):
        internal(request)
        data = await request.json()
        state = data.get('state')
        if state not in ('ready','done','failed'): raise HTTPException(400)
        snapshot = data.get('snapshot')
        if state != 'failed' and (not isinstance(snapshot,dict) or set(snapshot) != {'prepaid','subsidy','total','updated','room'} or any(not isinstance(v,str) or len(v)>200 for v in snapshot.values())): raise HTTPException(400)
        with connect(identity.db) as db:
            db.execute('BEGIN IMMEDIATE')
            job=db.execute('SELECT * FROM electric_jobs WHERE id=? AND lease=?',(data.get('id'),data.get('lease'))).fetchone()
            if not valid_job(db,job): raise HTTPException(409)
            if (state=='ready' and job['state']!='validating') or (state=='done' and job['state'] not in ('queued','processing')): raise HTTPException(409)
            encoded=json.dumps(snapshot,ensure_ascii=False) if snapshot else None
            db.execute('UPDATE electric_jobs SET state=?,snapshot=?,payload=CASE WHEN ? THEN NULL ELSE payload END,lease=NULL,lease_until=0 WHERE id=?', (state,encoded,state in ('done','failed'),job['id']))
            if state=='done':
                db.execute('INSERT OR REPLACE INTO electric_bindings VALUES(?,?,?,?,?,?)',(job['user_id'],job['qq'],job['id'],'active',encoded,time.time()))
        return {'ok':True}

    @router.post(B + '/health')
    async def health(request: Request):
        internal(request)
        data=await request.json()
        if data.get('state') not in ('active','auth','meter'): raise HTTPException(400)
        with connect(identity.db) as db:
            db.execute('UPDATE electric_bindings SET state=? WHERE version=?',(data['state'],data.get('version')))
        return {'ok':True}
    return router
