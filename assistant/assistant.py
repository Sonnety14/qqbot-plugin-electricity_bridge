"""Windows pilot helper. No proxy changes, no raw traffic files, no TLS interception."""
import asyncio
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading

HOST = 'wx.cdzht.com'
from configuration import load_upload_url, save_origin


def capture():
    # Connection ticket is passed through a private pipe, never argv/environment/files.
    upload_url = load_upload_url()
    token = json.loads(sys.stdin.readline())['token']
    from mitmproxy import options
    from mitmproxy.tools.dump import DumpMaster
    from http.cookies import SimpleCookie
    from html import unescape
    import httpx
    import ipaddress

    def report(state):
        print(json.dumps({'state':state}), flush=True)

    names = {'WeChatAppEx.exe','Weixin.exe','WeChat.exe'}
    # Discover a currently configured loopback proxy process; never change its configuration.
    command = r'''$p=Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings';
if($p.ProxyEnable -eq 1){foreach($m in [regex]::Matches($p.ProxyServer,'(?:127\.0\.0\.1|localhost):(\d+)')){
Get-NetTCPConnection -State Listen -LocalPort ([int]$m.Groups[1].Value) -ErrorAction SilentlyContinue |
ForEach-Object {(Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName}}}'''
    try:
        r = subprocess.run(['powershell.exe','-NoProfile','-Command',command], capture_output=True, text=True, timeout=15, creationflags=0x08000000)
        for name in r.stdout.splitlines():
            if re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', name.strip()): names.add(name.strip()+'.exe')
    except Exception: pass
    addresses = {x[4][0] for x in socket.getaddrinfo(HOST,80,type=socket.SOCK_STREAM)}
    addresses = {ip for ip in addresses if ipaddress.ip_address(ip).is_global}
    if not addresses: raise RuntimeError('DNS unavailable')
    hosts = r'^(?:' + '|'.join(re.escape(x) for x in addresses|{HOST}) + r')(?::\d+)?$'

    async def run():
        with tempfile.TemporaryDirectory(prefix='electricity-bridge-') as directory:
            opts=options.Options(mode=['local:'+','.join(sorted(names))],listen_host='127.0.0.1',listen_port=0,
                allow_hosts=[hosts],confdir=directory)
            master=DumpMaster(opts,with_termlog=False,with_dumper=False)
            class Capture:
                busy=False
                def running(self): report('ready')
                def tls_clienthello(self,data): data.ignore_connection=True
                def request(self,flow):
                    if flow.request.scheme=='http' and flow.request.pretty_host.lower()==HOST and flow.request.method=='GET' and flow.request.path.split('?')[0]=='/meter_main':
                        for name in ('if-none-match','if-modified-since'):flow.request.headers.pop(name,None)
                        flow.request.headers['cache-control']='no-cache'
                async def response(self,flow):
                    if self.busy or flow.request.scheme!='http' or flow.request.pretty_host.lower()!=HOST or flow.request.method!='GET' or flow.request.path.split('?')[0]!='/meter_main' or flow.response.status_code!=200: return
                    if len(flow.response.raw_content or b'')>256000: return
                    page=flow.response.get_text(strict=False)
                    room=re.search(r'<span\b[^>]*\bid=[\"\x27]roomaddr[\"\x27][^>]*>(.*?)</span>',page,re.S|re.I)
                    if not room:return
                    cookie=SimpleCookie()
                    try:cookie.load(flow.request.headers.get('cookie',''))
                    except Exception:return
                    if 'connect.sid' not in cookie:return
                    self.busy=True
                    data={'cookie':'connect.sid='+cookie['connect.sid'].value,
                          'user_agent':flow.request.headers.get('user-agent','Mozilla/5.0'),
                          'room':unescape(re.sub(r'<[^>]+>','',room.group(1))).strip()}
                    try:
                        async with httpx.AsyncClient(timeout=20,trust_env=False) as client:
                            r=await client.post(upload_url,json=data,headers={'Authorization':'Bearer '+token})
                        report('uploaded' if r.status_code==200 else 'expired' if r.status_code in (401,409) else 'upload_failed')
                    except Exception:report('upload_failed')
                    finally:master.shutdown()
            master.addons.add(Capture())
            async def timeout():
                await asyncio.sleep(300);report('timeout');master.shutdown()
            timer=asyncio.create_task(timeout())
            try: await master.run()
            finally: timer.cancel()
    asyncio.run(run())


def gui(smoke_test=False):
    import ctypes
    handle=ctypes.windll.kernel32.GetConsoleWindow()
    if handle and not smoke_test:ctypes.windll.user32.ShowWindow(handle,0)
    import tkinter as tk
    from tkinter import ttk
    window=tk.Tk();window.title('电费连接助手');window.geometry('530x350');window.resizable(False,False)
    if smoke_test:window.withdraw()
    frame=ttk.Frame(window,padding=24);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='提供连接码的网站地址（HTTPS）').pack(anchor='w')
    website=ttk.Entry(frame,width=65);website.pack(fill='x',pady=(8,12))
    try:website.insert(0,load_upload_url().removesuffix('/tools/campus/electric/upload'))
    except Exception:pass
    ttk.Label(frame,text='粘贴网站生成的连接码').pack(anchor='w')
    code=ttk.Entry(frame,width=65);code.pack(fill='x',pady=(8,14))
    status=tk.StringVar(value='连接后，在微信打开电费余额页。')
    ttk.Label(frame,textvariable=status,wraplength=455).pack(anchor='w',pady=8)
    ttk.Label(frame,text='仅连接电费站点，5 分钟后自动停止。').pack(anchor='w',pady=6)
    buttons=ttk.Frame(frame);buttons.pack(fill='x',pady=10)
    process=None
    labels={'ready':'已准备好：请在微信进入电费余额页，并刷新一次。',
            'uploaded':'已连接。请回网站确认房间和余额，然后关闭助手。',
            'expired':'连接码已失效，请在网站重新生成。',
            'upload_failed':'提交失败，请检查网络并重新生成连接码。',
            'timeout':'等待已超时。请重新连接后打开微信余额页。'}
    def stop():
        nonlocal process
        p=process
        if p and p.poll() is None:
            subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,creationflags=0x08000000)
        process=None
    def update(message):
        if window.winfo_exists():status.set(message)
    def start():
        nonlocal process
        value=code.get().strip()
        if not re.fullmatch(r'ELECTRIC-[A-Za-z0-9_-]{43}',value):status.set('请复制完整的 ELECTRIC- 开头连接码。');return
        if process and process.poll() is None:return
        try:save_origin(website.get())
        except ValueError:status.set('请输入可信的 HTTPS 网站根地址，不要填写账号页路径。');return
        except OSError:status.set('无法保存网站地址，请先解压到可写文件夹，再打开助手。');return
        start_button.config(state='disabled');status.set('正在准备连接…');code.delete(0,'end')
        args=[sys.executable,'--capture'] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve()),'--capture']
        process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf8',creationflags=0x08000000)
        process.stdin.write(json.dumps({'token':value[9:]})+'\n');process.stdin.close()
        p=process
        def watch():
            terminal=False
            for line in p.stdout:
                try:state=json.loads(line).get('state')
                except Exception:continue
                if state in labels:
                    terminal=state!='ready';window.after(0,update,labels[state])
            p.wait()
            if not terminal:window.after(0,update,'连接组件未能运行，请关闭后重试；如提示管理员权限，请允许。')
            window.after(0,lambda:start_button.config(state='normal'))
        threading.Thread(target=watch,daemon=True).start()
    start_button=ttk.Button(buttons,text='开始连接',command=start);start_button.pack(side='left')
    def close():stop();window.destroy()
    ttk.Button(buttons,text='关闭',command=close).pack(side='right')
    window.protocol('WM_DELETE_WINDOW',close)
    if smoke_test:
        window.update_idletasks();assert website.winfo_exists() and code.winfo_exists()
        window.destroy();print('PASS packaged GUI without starting capture',flush=True);return
    window.mainloop()


if __name__=='__main__':
    if '--self-test' in sys.argv:
        from mitmproxy import options
        from mitmproxy.tools.dump import DumpMaster
        import mitmproxy_windows, tkinter, httpx
        opts=options.Options(mode=['local:WeChatAppEx.exe'],allow_hosts=[r'^wx\.cdzht\.com$'])
        print('PASS packaged imports and options',flush=True)
    elif '--self-test-gui' in sys.argv:
        gui(smoke_test=True)
    elif '--capture' in sys.argv:
        try:capture()
        except Exception:print(json.dumps({'state':'error'}),flush=True)
    else:gui()
