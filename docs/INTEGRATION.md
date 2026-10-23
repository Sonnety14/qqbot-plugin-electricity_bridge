# 网站接入契约

`integration/router.py` 是 FastAPI 路由适配模块，不含账号系统或可直接启动的服务器。它不导入原私有博客代码，但要求宿主实现以下接口。

```python
from integration.router import build_electric_router
app.include_router(build_electric_router(
    identity=identity_adapter,
    origin="https://your-site.example",
    store=rate_limit_adapter,
    bridge_token=server_master_secret,
    pilot_qq=configured_pilot_qq,
))
```

示例变量须由部署环境提供，不能把服务端密钥写入源码。`bridge_token` 为高强度服务端主密钥，不是直接发给机器人的令牌。

## 宿主接口

- `identity.db`：SQLite 文件路径。
- `identity.load_session(cookie_value)`：无效、撤销或过期会话返回 None；有效会话返回 `id`、`verified_at`、`csrf`、`user_auth_version`。宿主必须实际验证 cookie，不得直接信任请求中的用户 ID。
- `store.limit(key, limit)`：线程安全的限流；在宿主规定的短时间窗口内返回是否允许。本模块以此限制连接码创建，宿主还须配置全局/IP 限流。
- 默认会话 Cookie 为 `__Host-site_session`，可用 `session_cookie` 参数指定；应使用 Secure、HttpOnly、Path=/ 等正确配置。
- 数据库已有 `users(id,auth_version,status)`、`email_credentials(user_id,verified_at)` 和 `campus_qq_bindings(user_id,qq)`。这里保留历史表名及路由名兼容协议，不代表依赖校园插件。`status='active'` 表示可用账号；`qq` 必须通过真实验证流程取得。
- 数据库同级 `campus-media/electric-assistant.zip` 是可选下载产物；应由部署者放置并设置服务账号可读权限。

路由创建 `electric_jobs` 和 `electric_bindings`。它只是单账号试用限制，不是完整多租户系统。

## 接口

| 路径 | 方法/鉴权 | 用途 |
| --- | --- | --- |
| `/tools/campus/electric/status` | GET，会话 | 当前任务、房间结果、正式绑定状态，不返回 Cookie |
| `/tools/campus/electric/start` | POST，会话 + Origin + CSRF | 签发一次性 `ELECTRIC-` 连接码 |
| `/tools/campus/electric/upload` | POST，一次性 Bearer | 助手提交 cookie、user_agent、room |
| `/tools/campus/electric/confirm` | POST，会话 + Origin + CSRF | 本人确认已验证房间；body 为任务 id |
| `/tools/campus/electric/assistant.zip` | GET，会话 + 试用账号 | 下载助手 |
| `/comments/bridge/campus/electric/work` | POST，私网 + scoped Bearer | 机器人取得验证/安装任务 |
| `/comments/bridge/campus/electric/result` | POST，私网 + scoped Bearer | 携带任务 id 和 lease 回报结果 |
| `/comments/bridge/campus/electric/health` | POST，私网 + scoped Bearer | 按绑定版本更新 active/auth/meter 状态 |

所有 JSON 路由由宿主限制请求体大小（建议 16 KiB），设置 no-store；不要记录 Authorization、Cookie、请求体、连接码及会话。关闭能泄露请求字段的诊断日志。公网代理应直接拒绝整个内部 bridge 前缀，不能只靠隐藏路径。

机器人配置 `bridge_token` 是：

```python
hmac.new(server_master_secret.encode(), b"campus-bindings-v1", hashlib.sha256).hexdigest()
```

密钥只通过私有配置传递。插件的 `backend_origin` 要求是私有 IP 的 HTTP origin（无路径）；`backend_host` 指定站点虚拟主机；`account_url` 可指定 HTTPS 更新页面。不再自动读取其他插件配置。

## 前端需要做什么

本项目没有复制整个私有账号页面。集成方应在自己的账号页面实现：生成连接码、展示下载链接、轮询状态、显示 `ready` 的房间/余额/时间、用户点击后调用 confirm，并展示 done/failed/expired。不要自动替用户确认。

任务流程为 waiting → validating → ready → queued → done；失败为 failed，超时为 expired。`processing` 是兼容保留状态。一次性上传使 token 失效；账号授权版本变化后旧任务不可继续。待处理 Cookie 使用由服务器主密钥派生的 Fernet 密钥加密，完成/失败/超时清除。

机器人最终凭据在文件中受访问权限保护，并非数据库加密。现阶段正式查询仍是单账号，插件配置的 QQ 必须与网站试用 QQ 一致，否则拒绝安装任务。不要取消试用限制就宣称支持多人。
