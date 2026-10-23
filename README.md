# Electricity Bridge：电费查询插件与 Windows 连接助手

通过用户自己的微信电费会话读取余额，使用 AstrBot 发送每日低余额 QQ 提醒。Windows 助手用于把正常登录后的电费会话交给用户信任的网站，减少手工抓包步骤。

本项目提供 AstrBot 电费提醒插件、Windows 连接助手和网站绑定接口。当前支持一个配置的 QQ 和一份电费会话，适合个人或单房间部署。源码仓库包含代码、配置示例和测试；Windows 免安装助手可从 [Releases](https://github.com/Sonnety14/qqbot-plugin-electricity_bridge/releases) 下载。下载包不含真实账号、会话或预配置的网站地址。

关联线上版本已完成用户实际操作的首次绑定、网站确认、模拟授权失效后的更新恢复和 QQ 状态查询。本仓库的配置拆分版本通过 18 项离线测试；部署到新环境后仍需进行端到端验证。运营方自然会话过期时间尚未确定。

## 项目包含什么

```text
assistant/                        Windows 助手及网站地址配置示例
plugin/astrbot_plugin_electricity/ AstrBot 插件
integration/router.py             FastAPI 网站绑定接口适配模块
examples/                         虚构的凭据格式
scripts/                          本地构建、打包和诊断辅助脚本
tests/                            离线测试及 AstrBot 环境回归脚本
docs/                             网站适配、发布前检查记录
```

插件默认北京时间每天 09:00 只读查询，余额严格低于 20 元提醒；查询异常最多尝试三次，发送前预留通知记录，避免超时后重复发送。收到授权失效或房间变化时暂停查询。私聊“电费状态”或“电费查询”读取最近一次缓存结果，不会立即向运营方发起额外查询。

网站适配模块提供一次性连接码、加密暂存、房间确认和桥接队列。**它不是可直接启动的完整网站**：登录、邮箱验证、QQ 绑定、限流和反向代理需要宿主应用提供，见 [网站接入说明](docs/INTEGRATION.md)。不开启网站桥接时，可以用自己的凭据文件运行查询插件。

## 普通用户：通过助手绑定

需要网站运营者事先完成网站接口接入并开放账号绑定权限。通用助手首次使用可直接填写可信网站的 HTTPS 根地址，无需编辑文件。下载和运行步骤见 [Windows 使用说明](docs/WINDOWS_GUIDE.md)。

1. 登录提供方网站，绑定本人 QQ，进入“绑定电费”。
2. 下载并解压助手，保留整个程序文件夹。
3. 网站生成连接码，复制 `ELECTRIC-` 开头的完整字符。
4. 打开助手，填写提供连接码的网站 HTTPS 根地址，粘贴连接码，点击“开始连接”。
5. 显示已准备好后，在 Windows 微信进入本人已绑定房间的电费余额页并刷新。
6. 助手提示已连接后，回网站确认房间、余额和数据更新时间，点击“确认绑定”。
7. 完成后关闭助手。服务器负责后续每天查询，不需要一直开着助手。

连接码只用来授权一次提交，不是电费网站的 Cookie。连接码 10 分钟有效，助手等待最多 5 分钟。授权失效时再次在微信正常进入余额页，重新生成连接码并重复操作。不能保证刷新一次页面就永久续期。

助手不修改系统代理，不需要用户安装根证书，不保存原始抓包；HTTPS 不解密。会自动识别微信进程和系统代理指向的本机代理进程。不同微信、代理及 Windows 环境仍需实测；若没有连接信号，按下面的开发者诊断流程定位。

## 为什么需要抓包、获取什么信息、用于什么

当前适配的电费服务是 `wx.cdzht.com`，余额页面为：

```text
GET http://wx.cdzht.com/meter_main
```

微信授权返回运营方自己的站点。浏览器会带上登录后的 `connect.sid` 会话 Cookie 请求余额页，余额直接出现在 HTML 中，而不是一个已经公开给本站调用的 JSON 接口。

Cookie 带 HttpOnly，普通网页脚本不能读取；本站也不能读取微信内置浏览器中另一域名的 Cookie。助手因此在用户明确启动后，观察本人正常打开余额页的 HTTP 请求和响应。

| 信息 | 在哪里获得 | 用途 | 保存方式 |
| --- | --- | --- | --- |
| `connect.sid` | 成功余额请求的 `Cookie` 请求头 | 让插件以本人现有会话执行只读查询 | 网站短时加密暂存；机器人凭据文件受权限保护 |
| `User-Agent` | 同一请求的请求头 | 使用一致的客户端标识；它本身不是登录凭据 | 随凭据保存 |
| 房间完整文字 | 余额页 HTML 中 `id="roomaddr"` 的元素 | 确认监控的电表，防止会话选中别的房间后继续提醒 | 随凭据和查询结果保存 |
| 三项余额和数据更新时间 | 同一响应的 HTML | 生成状态和低余额提醒，检查数据是否陈旧 | 查询记录；不保存原始 HTML |
| 网站连接码 | 自己的网站生成，不来自抓包 | 关联已登录网站账号与本次助手上传 | 服务器只存摘要，提交后作废 |

Cookie 是敏感登录凭据，即便插件仅执行只读 GET，也不能保证该 Cookie 在运营方站点只有只读权限。不要发进 QQ 群、聊天记录、Issues、截图或 Git 仓库。上游当前使用 HTTP；助手向自建网站使用 HTTPS，不能消除上游明文传输的限制。

不需要微信密码、公众号 AppSecret、OAuth `code`、付款信息、完整 Cookie 列表或全量 HAR。尤其不要复制授权回调 URL 中的一次性 `code` 当作长期查询凭据。

## 开发者：如何手工抓包

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

插件读取 `credentials.json`，向固定余额地址发 GET，携带该 Cookie 和 User-Agent，不跟随授权跳转，不提交支付或选择房间表单。解析余额之前严格比对房间；数据超过 48 小时或明显来自未来时，提示核对而不据此报欠费。

凭据失效不能靠复制旧 Cookie 修复。用户需正常重新授权，取得新会话，再更新文件或通过助手重新绑定。每日访问是否延长运营方会话有效期尚未验证。

## 安装 AstrBot 插件

1. 在项目目录执行 `python scripts/package_plugin.py`，得到 `dist/astrbot_plugin_electricity.zip`。
2. 在 AstrBot 插件管理界面上传该 ZIP。只打包源文件，不含凭据。
3. 配置 `platform_id` 为你实际的 QQ 平台标识，`qq` 为接收人的已确认 QQ，设置阈值、北京时间整点，启用插件。默认不含任何真实 QQ。
4. 不使用网站桥接时，把本人凭据放入 `StarTools.get_data_dir('astrbot_plugin_electricity')` 所对应目录的 `credentials.json`；实际宿主机路径由 AstrBot 的数据挂载决定。
5. 使用网站时，按 [网站接入说明](docs/INTEGRATION.md) 配置 `bridge_enabled`、私网地址、Host 和专用桥接令牌。令牌仅在服务端配置，不放入助手。

`enabled=false` 停止日常查询；`bridge_enabled=false` 停止网站桥接轮询。要完全停用插件，在 AstrBot 中停用它。

## 配置和构建助手

用户可在助手界面填写可信的 HTTPS 网站根地址，程序仅保存此地址。部署者也可将 `assistant/config.example.json` 复制为 `assistant/config.json` 并填写 `website_origin`。默认 `example.invalid` 会被拒绝；连接码不能改变上传目的地，用户不需要配置代理。

```powershell
.\.venv\Scripts\python.exe assistant/assistant.py
# 构建时先激活同一环境
.\.venv\Scripts\Activate.ps1
.\scripts\build_assistant.ps1
```

构建产物在 `dist/ElectricityAssistant/`。保留 `_internal`。可以不带 `config.json` 分发，由用户首次填写网站；也可由运营者预配置可信网站。构建脚本刻意不自动复制真实配置。连接码永远不能改变上传地址。更新过网址的包应由提供方重新检查和分发，不让用户从不可信来源获取配置。

官方 Releases 提供本独立项目构建的通用 Windows x64 包、使用说明、SHA256 清单及第三方源码材料；不包含个人部署配置。

## 测试与待验收

```powershell
py -3.12 -m venv .venv-test
.\.venv-test\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv-test\Scripts\python.exe -m pytest tests -q
```

本次独立目录的 18 项离线测试通过，包含用最小 AstrBot API 替身验证的插件逻辑；详细结果见 [验证记录](docs/VALIDATION.md)。离线测试不抓包、不发送 QQ、不访问真实电费服务。直接在真实 AstrBot 环境运行的回归入口是 `tests/check_astrbot_runtime.py`，需要已安装 AstrBot。

部署后建议依次验证首次绑定、房间确认、QQ 状态和受控失效恢复；跨 Windows 环境及自然会话过期仍需观察。模拟失效成功不代表已验证自然过期。后续事项见 [维护清单](docs/RELEASE_CHECKLIST.md)。

## 凭据和发布规则

`.gitignore` 排除了运行凭据、数据库、日志、抓包、环境和构建产物，但忽略规则不是泄露检测。新增文件前检查内容；禁止上传历史原始抓包、生产配置及数据库备份。

项目仓库：[Sonnety14/qqbot-plugin-electricity_bridge](https://github.com/Sonnety14/qqbot-plugin-electricity_bridge)。

Windows Release 附带运行依赖、第三方许可声明和对应源码材料，不预置站点或账号。源码尚未指定开源许可证，公开可见不代表授予额外使用或再分发许可。第三方依赖适用各自许可证，见 [第三方说明](THIRD_PARTY_NOTICES.md)。
