# GPT Team Member Manager

一个专注于 ChatGPT Team 账号与成员管理的轻量 FastAPI 控制台。

项目保留 Team 导入、OAuth 授权、成员邀请和状态同步等核心能力，移除了兑换码、质保、体验池、公告、库存 Webhook、Codex 额度和 CliproxyAPI 推送等非成员管理功能。

## 功能

- 管理员登录与密码修改
- 单个、批量及 JSON 导入 Team
- 浏览器打开 OpenAI OAuth 授权
- 自动接收 OAuth 回调并导入 Team
- 自动回调失败时手动粘贴回调地址
- 直接粘贴 ChatGPT Session JSON 或 Session Token 导入
- 查看已加入成员和待接受邀请
- 以普通成员或管理员身份发送邀请，默认普通成员
- 删除成员与撤回邀请
- Team 单个或批量刷新、批量删除
- Token 预刷新与 Team 周期同步
- HTTP、SOCKS5、SOCKS5H 代理
- 深色与暖色主题

## 本地运行

需要 Python 3.10 或更高版本。

```powershell
git clone https://github.com/momoi6661/team-manage-refresh-main.git
cd team-manage-refresh-main

python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe app\main.py
```

打开：<http://localhost:8008>

OAuth 发起时程序会临时监听 `1455`，收到回调、取消授权或等待超时后会自动释放：

```text
http://localhost:1455/auth/callback
```

若自动回调失败，可在导入窗口展开“自动读取失败？手动粘贴回调”，粘贴浏览器地址栏中的完整回调地址。

导入窗口提供彼此独立的“OAuth 授权”和“Token / Session”页签。不方便完成 OAuth 验证时，可直接进入第二个页签粘贴 ChatGPT 会话 JSON，无需发起授权或填写回调。系统支持自动识别 `accessToken`、`sessionToken`、`user.email` 和 `account.id`；只提供 Session Token 时，后端会通过已配置的代理换取当前 Access Token。

## Docker Compose

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

- 管理页面：<http://localhost:8008>
- OAuth 回调：<http://localhost:1455/auth/callback>（仅授权期间临时占用）
- 数据目录：`./data`

Docker 部署会挂载本机 Docker socket，仅用于在发起 OAuth 时创建一次性回调辅助容器。辅助容器收到回调、取消授权或等待 10 分钟后退出，随后释放 `1455`。

### Docker 代理地址

容器中的 `127.0.0.1` 指向容器自身。若代理运行在宿主机，请在“代理与系统”中填写：

```text
http://host.docker.internal:7890
```

端口请按实际代理软件调整。Compose 已配置 `host.docker.internal:host-gateway`。

## 配置

复制 `.env.example` 为 `.env` 后，至少修改：

```dotenv
SECRET_KEY=请替换为足够长的随机字符串
ADMIN_PASSWORD=请替换默认管理员密码
```

已有数据库中的管理员密码不会因修改 `ADMIN_PASSWORD` 自动覆盖，可在控制台中修改密码。

## 数据安全

- `.env`、SQLite 数据库、日志和虚拟环境默认不会提交到 Git。
- Access Token、Refresh Token 和 Session Token 会加密保存到本地数据库。
- 不要在 Issue、截图或日志中公开 Token、OAuth code、密码或数据库文件。

## 验证

```powershell
.\.venv\Scripts\python.exe -m compileall -q app
node --check app\static\js\main.js
```

## License

[MIT](LICENSE)
