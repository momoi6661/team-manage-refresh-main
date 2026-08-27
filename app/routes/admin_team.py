"""仅包含 Team 与成员管理的管理员路由。"""
import json
import logging
import re
import time
from html import escape
from typing import Literal, Optional
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.database import AsyncSessionLocal, get_db
from app.dependencies.auth import require_admin
from app.services.chatgpt import chatgpt_service
from app.services.oauth_listener import oauth_callback_listener
from app.services.settings import DEFAULT_UI_THEME, settings_service
from app.services.team import team_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])
callback_router = APIRouter(tags=["oauth-callback"])

OAUTH_FLOW_TTL_SECONDS = 10 * 60
_oauth_import_flows: dict[str, dict] = {}


class TeamImportRequest(BaseModel):
    import_type: str
    access_token: Optional[str] = None
    id_token: Optional[str] = None
    refresh_token: Optional[str] = None
    session_token: Optional[str] = None
    client_id: Optional[str] = None
    email: Optional[str] = None
    account_id: Optional[str] = None
    content: Optional[str] = None
    pool_type: str = "normal"


class OAuthAuthorizeRequest(BaseModel):
    client_id: str = "app_EMoamEEZ73f0CkXaXp7hrann"
    redirect_uri: str = app_settings.oauth_redirect_uri
    scope: str = "openid email profile offline_access"
    audience: Optional[str] = None
    codex_cli_simplified_flow: bool = True
    id_token_add_organizations: bool = True


class OAuthCallbackParseRequest(BaseModel):
    callback_text: str
    code_verifier: Optional[str] = None
    expected_state: Optional[str] = None
    client_id: Optional[str] = "app_EMoamEEZ73f0CkXaXp7hrann"
    redirect_uri: str = app_settings.oauth_redirect_uri


class AddMemberRequest(BaseModel):
    email: str
    role: Literal["standard-user", "admin"] = "standard-user"


class TeamUpdateRequest(BaseModel):
    email: Optional[str] = None
    account_id: Optional[str] = None
    access_token: Optional[str] = None
    id_token: Optional[str] = None
    refresh_token: Optional[str] = None
    session_token: Optional[str] = None
    client_id: Optional[str] = None
    team_name: Optional[str] = None
    status: Optional[str] = None


class BulkActionRequest(BaseModel):
    ids: list[int]


class ProxyConfigRequest(BaseModel):
    enabled: bool
    proxy: str = ""


class LogLevelRequest(BaseModel):
    level: str


class TokenRefreshSettingsRequest(BaseModel):
    interval_minutes: int = Field(30, ge=5, le=1440)
    window_hours: int = Field(2, ge=1, le=24)
    client_id: str = ""


class TeamAutoRefreshSettingsRequest(BaseModel):
    enabled: bool = True
    interval_hours: int = Field(12, ge=1, le=168)
    refresh_interval_days: int = Field(7, ge=1, le=30)


class UiThemeSettingsRequest(BaseModel):
    theme: Literal["ocean", "warm"] = DEFAULT_UI_THEME


async def _ui_theme(db: AsyncSession) -> str:
    return settings_service.normalize_ui_theme(
        await settings_service.get_setting(db, "ui_theme", DEFAULT_UI_THEME)
    )


def _prune_oauth_flows() -> None:
    cutoff = time.monotonic() - OAUTH_FLOW_TTL_SECONDS
    for state, flow in list(_oauth_import_flows.items()):
        if flow.get("created_at", 0) < cutoff:
            _oauth_import_flows.pop(state, None)


def _callback_page(title: str, message: str, success: bool) -> HTMLResponse:
    color = "#16a34a" if success else "#dc2626"
    icon = "✓" if success else "!"
    body = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>
<style>body{{margin:0;background:#f4f7fb;color:#172033;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;display:grid;place-items:center;min-height:100vh}}.card{{width:min(420px,calc(100% - 40px));background:#fff;border:1px solid #e5eaf1;border-radius:18px;padding:34px;box-shadow:0 18px 50px rgba(23,32,51,.12);text-align:center}}.icon{{width:56px;height:56px;margin:0 auto 18px;border-radius:50%;display:grid;place-items:center;background:{color};color:#fff;font-size:30px;font-weight:700}}h1{{font-size:22px;margin:0 0 10px}}p{{color:#667085;line-height:1.7;margin:0}}</style></head>
<body><main class="card"><div class="icon">{icon}</div><h1>{escape(title)}</h1><p>{escape(message)}</p></main>
<script>if(window.opener){{setTimeout(()=>window.close(),1800);}}</script></body></html>"""
    return HTMLResponse(body, status_code=200 if success else 400)


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
    status_filter: Optional[str] = None,
    legacy_status: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    if status_filter is None:
        status_filter = legacy_status
    teams = await team_service.get_all_teams(
        db, page=page, per_page=per_page, search=search, status=status_filter, pool_type="normal"
    )
    stats = await team_service.get_stats(db, pool_type="normal")
    from app.main import templates
    return templates.TemplateResponse(request, "admin/index.html", {
        "request": request,
        "user": current_user,
        "active_page": "dashboard",
        "ui_theme": await _ui_theme(db),
        "teams": teams.get("teams", []),
        "stats": {"total_teams": stats["total"], "available_teams": stats["available"]},
        "search": search,
        "status_filter": status_filter,
        "pagination": {
            "current_page": teams.get("current_page", page),
            "total_pages": teams.get("total_pages", 1),
            "total": teams.get("total", 0),
            "per_page": per_page,
        },
    })


@router.post("/teams/{team_id}/delete")
async def delete_team(team_id: int, db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    result = await team_service.delete_team(team_id, db)
    return JSONResponse(status_code=200 if result.get("success") else 400, content=result)


@router.get("/teams/{team_id}/info")
async def team_info(team_id: int, db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    result = await team_service.get_team_info(team_id, db)
    return JSONResponse(status_code=200 if result.get("success") else 404, content=result)


@router.post("/teams/{team_id}/update")
async def update_team(team_id: int, data: TeamUpdateRequest, db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    result = await team_service.update_team(team_id=team_id, db_session=db, **data.model_dump())
    return JSONResponse(status_code=200 if result.get("success") else 400, content=result)


@router.post("/teams/import")
async def import_team(data: TeamImportRequest, db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    if data.import_type == "single":
        if not any((data.access_token, data.refresh_token, data.session_token)):
            return JSONResponse(status_code=400, content={"success": False, "error": "必须提供一种 Token"})
        result = await team_service.import_team_single(
            access_token=data.access_token, id_token=data.id_token,
            refresh_token=data.refresh_token, session_token=data.session_token,
            client_id=data.client_id, email=data.email, account_id=data.account_id,
            pool_type="normal", db_session=db,
        )
        return JSONResponse(status_code=200 if result.get("success") else 400, content=result)

    if data.import_type not in {"batch", "json"}:
        return JSONResponse(status_code=400, content={"success": False, "error": "无效的导入类型"})

    async def progress():
        iterator = (
            team_service.import_team_json(data.content, db, pool_type="normal")
            if data.import_type == "json"
            else team_service.import_team_batch(data.content, db, pool_type="normal")
        )
        async for item in iterator:
            yield json.dumps(item, ensure_ascii=False) + "\n"

    return StreamingResponse(progress(), media_type="application/x-ndjson")


@router.post("/oauth/openai/authorize")
async def oauth_authorize(data: OAuthAuthorizeRequest, _: dict = Depends(require_admin)):
    auth = chatgpt_service.create_oauth_authorize_url(
        client_id=data.client_id.strip(), redirect_uri=data.redirect_uri.strip(),
        scope=data.scope.strip(), audience=data.audience.strip() if data.audience else None,
        codex_cli_simplified_flow=data.codex_cli_simplified_flow,
        id_token_add_organizations=data.id_token_add_organizations,
    )
    return {"success": True, "data": {**auth, "client_id": data.client_id.strip()}}


@router.post("/oauth/openai/start-import")
async def start_oauth_import(data: OAuthAuthorizeRequest, user: dict = Depends(require_admin)):
    """创建一次自动回调并导入 Team 的 OAuth 流程。"""
    _prune_oauth_flows()
    client_id = data.client_id.strip()
    redirect_uri = data.redirect_uri.strip()
    auth = chatgpt_service.create_oauth_authorize_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=data.scope.strip(),
        audience=data.audience.strip() if data.audience else None,
        codex_cli_simplified_flow=data.codex_cli_simplified_flow,
        id_token_add_organizations=data.id_token_add_organizations,
    )
    listener_result = await oauth_callback_listener.start()
    if not listener_result["success"]:
        return JSONResponse(status_code=409, content=listener_result)
    _oauth_import_flows[auth["state"]] = {
        "created_at": time.monotonic(),
        "status": "waiting",
        "code_verifier": auth["code_verifier"],
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "username": user.get("username", "admin"),
    }
    return {"success": True, "data": {
        "authorize_url": auth["authorize_url"],
        "state": auth["state"],
        "code_verifier": auth["code_verifier"],
        "client_id": client_id,
    }}


@router.get("/oauth/openai/import-status/{state}")
async def oauth_import_status(state: str, _: dict = Depends(require_admin)):
    _prune_oauth_flows()
    flow = _oauth_import_flows.get(state)
    if not flow:
        return JSONResponse(status_code=404, content={"success": False, "error": "授权任务已过期，请重新授权"})
    payload = {
        "success": True,
        "status": flow["status"],
        "message": flow.get("message"),
        "error": flow.get("error"),
    }
    if flow["status"] in {"success", "failed"}:
        _oauth_import_flows.pop(state, None)
    return payload


@router.post("/oauth/openai/cancel-import/{state}")
async def cancel_oauth_import(state: str, _: dict = Depends(require_admin)):
    """取消尚未收到回调的 OAuth 导入任务。"""
    _prune_oauth_flows()
    flow = _oauth_import_flows.get(state)
    if not flow:
        await oauth_callback_listener.stop()
        return JSONResponse(status_code=404, content={"success": False, "error": "授权任务已结束或过期"})

    current_status = flow["status"]
    if current_status != "waiting":
        return {"success": True, "cancelled": False, "status": current_status}

    _oauth_import_flows.pop(state, None)
    await oauth_callback_listener.stop()
    return {"success": True, "cancelled": True, "status": "cancelled"}


@callback_router.get("/auth/callback", response_class=HTMLResponse)
async def automatic_oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """接收浏览器 OAuth 回调，自动兑换 Token 并导入 Team。"""
    _prune_oauth_flows()
    flow = _oauth_import_flows.get(state or "")
    if not state or not flow:
        return _callback_page("授权任务无效", "授权状态不存在或已经过期，请返回控制台重新发起授权。", False)
    if error:
        message = error_description or error
        flow.update(status="failed", error=f"OpenAI 授权失败：{message}")
        return _callback_page("授权未完成", message, False)
    if not code:
        flow.update(status="failed", error="回调中缺少授权 code")
        return _callback_page("授权回调不完整", "没有收到授权 code，请重新发起授权。", False)
    if flow["status"] != "waiting":
        return _callback_page("授权已处理", "本次授权已经处理，请返回控制台查看结果。", flow["status"] == "success")

    flow["status"] = "processing"
    exchange = await chatgpt_service.exchange_oauth_code(
        code,
        flow["client_id"],
        flow["redirect_uri"],
        flow["code_verifier"],
        db,
        identifier=f"oauth_{flow['username']}",
    )
    if not exchange.get("success"):
        flow.update(status="failed", error=exchange.get("error") or "code 换 token 失败")
        return _callback_page("Token 获取失败", flow["error"], False)

    result = await team_service.import_team_single(
        access_token=exchange.get("access_token"),
        id_token=exchange.get("id_token"),
        refresh_token=exchange.get("refresh_token"),
        client_id=flow["client_id"],
        db_session=db,
        pool_type="normal",
    )
    if not result.get("success"):
        flow.update(status="failed", error=result.get("error") or "Team 导入失败")
        return _callback_page("Team 导入失败", flow["error"], False)

    flow.update(status="success", message=result.get("message") or "Team 已自动导入")
    return _callback_page("Team 导入成功", "授权信息已读取并完成导入，可以返回管理页面。", True)


@router.post("/oauth/openai/parse-callback")
async def oauth_callback(data: OAuthCallbackParseRequest, db: AsyncSession = Depends(get_db), user: dict = Depends(require_admin)):
    text = data.callback_text.strip()
    parsed = urlparse(text)
    merged = {k: v[0] for source in (parse_qs(parsed.query), parse_qs(parsed.fragment)) for k, v in source.items() if v}
    if not merged:
        merged.update(dict(re.findall(r"([a-zA-Z_][a-zA-Z0-9_]*)=([^\s&]+)", text)))
    if data.expected_state and merged.get("state") != data.expected_state:
        return JSONResponse(status_code=400, content={"success": False, "error": "state 不匹配，请重新授权"})

    access_token = merged.get("access_token")
    refresh_token = merged.get("refresh_token")
    id_token = merged.get("id_token")
    client_id = merged.get("client_id") or data.client_id
    code = merged.get("code")
    if code and not access_token:
        if not data.code_verifier or not client_id:
            return JSONResponse(status_code=400, content={"success": False, "error": "缺少 code_verifier 或 client_id"})
        exchange = await chatgpt_service.exchange_oauth_code(
            code, client_id, data.redirect_uri.strip(), data.code_verifier.strip(), db,
            identifier=f"oauth_{user.get('username', 'admin')}",
        )
        if not exchange.get("success"):
            return JSONResponse(status_code=400, content=exchange)
        access_token, refresh_token, id_token = (
            exchange.get("access_token"), exchange.get("refresh_token"), exchange.get("id_token")
        )
    if not access_token and not refresh_token:
        return JSONResponse(status_code=400, content={"success": False, "error": "未解析到可用 Token 或 code"})
    return {"success": True, "data": {
        "access_token": access_token or "", "refresh_token": refresh_token or "",
        "id_token": id_token or "", "client_id": client_id or "", "raw": merged,
    }}


@router.get("/teams/{team_id}/members/list")
async def members(team_id: int, db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    result = await team_service.get_team_members(team_id, db)
    return JSONResponse(status_code=200 if result.get("success") else 400, content=result)


@router.post("/teams/{team_id}/members/add")
async def add_member(team_id: int, data: AddMemberRequest, db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    result = await team_service.add_team_member(team_id, data.email, db, role=data.role)
    return JSONResponse(status_code=200 if result.get("success") else 400, content=result)


@router.post("/teams/{team_id}/members/{user_id}/delete")
async def remove_member(team_id: int, user_id: str, db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    result = await team_service.delete_team_member(team_id, user_id, db)
    return JSONResponse(status_code=200 if result.get("success") else 400, content=result)


@router.post("/teams/{team_id}/invites/revoke")
async def revoke_invite(team_id: int, data: AddMemberRequest, db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    result = await team_service.revoke_team_invite(team_id, data.email, db)
    return JSONResponse(status_code=200 if result.get("success") else 400, content=result)


@router.post("/teams/{team_id}/enable-device-auth")
async def enable_device_auth(team_id: int, db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    result = await team_service.enable_device_code_auth(team_id, db)
    return JSONResponse(status_code=200 if result.get("success") else 400, content=result)


@router.post("/teams/batch-refresh")
async def batch_refresh(data: BulkActionRequest, _: dict = Depends(require_admin)):
    async def progress():
        yield json.dumps({"type": "start", "total": len(data.ids), "success_count": 0, "failed_count": 0}) + "\n"
        success_count = failed_count = 0
        async with AsyncSessionLocal() as db:
            for index, team_id in enumerate(data.ids, 1):
                result = await team_service.sync_team_info(team_id, db, force_refresh=True)
                if result.get("success"): success_count += 1
                else: failed_count += 1
                yield json.dumps({"type": "progress", "current": index, "total": len(data.ids),
                    "success_count": success_count, "failed_count": failed_count, "team_id": team_id,
                    "last_result": result}, ensure_ascii=False) + "\n"
        yield json.dumps({"type": "finish", "total": len(data.ids), "success_count": success_count,
            "failed_count": failed_count, "message": f"批量刷新完成: 成功 {success_count}, 失败 {failed_count}"}, ensure_ascii=False) + "\n"
    return StreamingResponse(progress(), media_type="application/x-ndjson")


@router.post("/teams/batch-delete")
async def batch_delete(data: BulkActionRequest, db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    results = [await team_service.delete_team(team_id, db) for team_id in data.ids]
    success_count = sum(bool(item.get("success")) for item in results)
    return {"success": True, "message": f"批量删除完成: 成功 {success_count}, 失败 {len(results)-success_count}",
            "success_count": success_count, "failed_count": len(results)-success_count}


@router.post("/teams/batch-enable-device-auth")
async def batch_device_auth(data: BulkActionRequest, db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    results = [await team_service.enable_device_code_auth(team_id, db) for team_id in data.ids]
    success_count = sum(bool(item.get("success")) for item in results)
    return {"success": True, "message": f"批量处理完成: 成功 {success_count}, 失败 {len(results)-success_count}",
            "success_count": success_count, "failed_count": len(results)-success_count}


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: AsyncSession = Depends(get_db), user: dict = Depends(require_admin)):
    proxy = await settings_service.get_proxy_config(db)
    from app.main import templates
    return templates.TemplateResponse(request, "admin/settings/index.html", {
        "request": request, "user": user, "active_page": "settings", "ui_theme": await _ui_theme(db),
        "proxy_enabled": proxy["enabled"], "proxy": proxy["proxy"],
        "log_level": await settings_service.get_log_level(db),
        "token_refresh_interval_minutes": await settings_service.get_setting(db, "token_refresh_interval_minutes", "30"),
        "token_refresh_window_hours": await settings_service.get_setting(db, "token_refresh_window_hours", "2"),
        "token_refresh_client_id": await settings_service.get_setting(db, "token_refresh_client_id", ""),
        "periodic_team_sync_enabled": await settings_service.get_setting(db, "periodic_team_sync_enabled", "true"),
        "periodic_team_sync_interval_hours": await settings_service.get_setting(db, "periodic_team_sync_interval_hours", "12"),
        "periodic_team_sync_days": await settings_service.get_setting(db, "periodic_team_sync_days", "7"),
    })


@router.get("/settings/ui-theme")
async def get_theme(db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    return {"success": True, "theme": await _ui_theme(db)}


@router.post("/settings/ui-theme")
async def set_theme(data: UiThemeSettingsRequest, db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    theme = settings_service.normalize_ui_theme(data.theme)
    await settings_service.update_setting(db, "ui_theme", theme)
    return {"success": True, "message": "系统配色已保存", "theme": theme}


@router.post("/settings/proxy")
async def set_proxy(data: ProxyConfigRequest, db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    result = await settings_service.update_proxy_config(db, data.enabled, data.proxy.strip())
    await chatgpt_service.clear_session()
    return {"success": bool(result), "message": "代理配置已保存" if result else None, "error": None if result else "保存失败"}


@router.post("/settings/log-level")
async def set_log_level(data: LogLevelRequest, db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    success = await settings_service.update_log_level(db, data.level)
    return {"success": bool(success), "message": "日志级别已保存" if success else None}


@router.post("/settings/token-refresh")
async def set_token_refresh(data: TokenRefreshSettingsRequest, db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    for key, value in (("token_refresh_interval_minutes", data.interval_minutes),
                       ("token_refresh_window_hours", data.window_hours), ("token_refresh_client_id", data.client_id.strip())):
        await settings_service.update_setting(db, key, str(value))
    from app.main import configure_proactive_refresh_job
    configure_proactive_refresh_job(data.interval_minutes)
    return {"success": True, "message": "Token 刷新配置已保存"}


@router.post("/settings/team-auto-refresh")
async def set_team_auto_refresh(data: TeamAutoRefreshSettingsRequest, db: AsyncSession = Depends(get_db), _: dict = Depends(require_admin)):
    for key, value in (("periodic_team_sync_enabled", str(data.enabled).lower()),
                       ("periodic_team_sync_interval_hours", data.interval_hours),
                       ("periodic_team_sync_days", data.refresh_interval_days)):
        await settings_service.update_setting(db, key, str(value))
    from app.main import configure_periodic_team_sync_job
    configure_periodic_team_sync_job(data.enabled, data.interval_hours)
    return {"success": True, "message": "Team 自动刷新配置已保存"}
