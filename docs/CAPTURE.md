# 手工连接诊断

只对自己的账号或明确授权的账号执行。这里是开发者诊断方法；普通用户优先使用已经配置好的助手。

### 1. 准备独立 Python 环境

在本项目目录使用 Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r assistant/requirements.txt
```

### 2. 限定站点和微信进程

mitmproxy 支持按进程名称或 PID 的本机捕获，参见 [官方 Local Capture 文档](https://docs.mitmproxy.org/stable/concepts/modes/#local-capture)。以下只允许电费域名及当前解析出的 IPv4 地址，并通过脚本保持 HTTPS 透传：

```powershell
$electricIPs = Resolve-DnsName wx.cdzht.com -Type A |
    Where-Object IPAddress | Select-Object -ExpandProperty IPAddress
$electricTargets = @('wx.cdzht.com') + @($electricIPs)
$electricPattern = '^(?:' + (($electricTargets | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')(:\d+)?$'
.\.venv\Scripts\mitmweb.exe --mode 'local:WeChatAppEx.exe,Weixin.exe,WeChat.exe' --allow-hosts $electricPattern --listen-host 127.0.0.1 --web-host 127.0.0.1 --web-port 8081 --set web_open_browser=false -s scripts/http_only.py
```

打开工具启动日志中给出的本机管理页面；有管理令牌时保留在本机，不分享地址。不要加 `-w` 导出完整抓包，不要开放管理页面到公网。Windows 可能要求管理员权限。此流程不需要访问 mitm.it 或安装根证书。

若微信进程名不同，在任务管理器确认实际名称后调整 `local:` 参数。若微信通过本机代理出站，捕获微信进程可能看不到真正的电费请求：确认代理监听端口对应的进程名称，将其追加到逗号分隔的进程列表；保留相同域名限制，不能改成无范围的全机捕获。助手会尝试自动完成这一步。

### 3. 正常打开余额页

从微信公众号进入自己的电费余额页，刷新，查找目标站点的 `GET /meter_main`，要求响应为 `200`，内容是当前房间余额。

- 如果是 `304`，响应没有正文。重新进入余额页，或在明确的开发环境中去掉该请求的 `If-None-Match` / `If-Modified-Since` 后刷新；助手已处理此情况。
- 如果重定向到微信授权，先让用户正常完成授权，再找新的成功余额请求。
- 如果只有 HTTPS 隧道，此流程不会解密它；不要假设已经拿到 HTTP 会话。
- 不要请求 `/changeR`、`/jcbd` 或 `/charge` 做测试：它们可能换房、解绑或充值，其中换房即使用 GET 也有副作用。

### 4. 提取最少信息

只从成功余额请求取 Cookie 中 `connect.sid` 这一项，格式是 `connect.sid=实际值`，不要带其他 Cookie；保留原始百分号编码，不额外 URL 解码。再取 `User-Agent`，以及 HTML 中 `roomaddr` 元素的可见文字（去掉标签并解码 HTML 实体）。

按下面格式保存到**自己部署环境的私有文件**，示例中的占位文字不可直接使用：

```json
{
  "cookie": "connect.sid=REPLACE_WITH_YOUR_OWN_SESSION",
  "user_agent": "REPLACE_WITH_CAPTURED_USER_AGENT",
  "room": "REPLACE_WITH_YOUR_OWN_ROOM_LABEL"
}
```

不要把文件放在公开静态资源目录。Linux 文件权限设为 0600，父目录仅服务账号可访问；Windows 使用 ACL 限制为自己及必要服务账号，不要仅依赖 `chmod`。操作完成后 Ctrl+C 停止抓包，关闭管理页面，不导出全量记录。

### 5. 插件如何使用这些信息

插件读取当前网站账号对应的加密凭据，向固定余额地址发 GET，携带该 Cookie 和 User-Agent，不跟随授权跳转，不提交支付或选择房间表单。解析余额之前严格比对房间；数据超过 48 小时或明显来自未来时，提示核对而不据此报欠费。

凭据失效不能靠复制旧 Cookie 修复。用户需正常重新授权，取得新会话，再更新文件或通过助手重新绑定。每日访问是否延长运营方会话有效期尚未验证。

