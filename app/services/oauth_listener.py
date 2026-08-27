"""按需启动并停止 OAuth 本地回调监听器。"""
import asyncio
import logging
from pathlib import Path
from urllib.parse import quote

import httpx

from app.config import settings

logger = logging.getLogger(__name__)
DOCKER_SOCKET = Path("/var/run/docker.sock")
CALLBACK_PORT = 1455
CALLBACK_TIMEOUT_SECONDS = 10 * 60


class OAuthCallbackListener:
    def __init__(self):
        self._local_server = None
        self._local_timeout_task = None

    async def start(self) -> dict:
        if DOCKER_SOCKET.exists():
            return await self._start_docker_helper()
        return await self._start_local_listener()

    async def stop(self) -> None:
        if DOCKER_SOCKET.exists():
            await self._remove_docker_helper()
        await self._stop_local_listener()

    async def _docker_request(self, method: str, path: str, **kwargs) -> httpx.Response:
        transport = httpx.AsyncHTTPTransport(uds=str(DOCKER_SOCKET))
        async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=10) as client:
            return await client.request(method, path, **kwargs)

    async def _remove_docker_helper(self) -> None:
        name = quote(settings.oauth_callback_container, safe="")
        try:
            response = await self._docker_request("DELETE", f"/containers/{name}?force=true")
            if response.status_code not in {204, 404}:
                logger.warning("停止 OAuth 回调辅助容器失败: %s", response.text)
        except Exception as exc:
            logger.warning("停止 OAuth 回调辅助容器失败: %s", exc)

    async def _start_docker_helper(self) -> dict:
        await self._remove_docker_helper()
        name = quote(settings.oauth_callback_container, safe="")
        payload = {
            "Image": settings.oauth_callback_image,
            "Cmd": ["python", "-m", "app.oauth_callback_bridge"],
            "ExposedPorts": {f"{CALLBACK_PORT}/tcp": {}},
            "HostConfig": {
                "AutoRemove": False,
                "PortBindings": {
                    f"{CALLBACK_PORT}/tcp": [
                        {"HostIp": "0.0.0.0", "HostPort": str(CALLBACK_PORT)}
                    ]
                },
            },
        }
        try:
            created = await self._docker_request("POST", f"/containers/create?name={name}", json=payload)
            if created.status_code != 201:
                return {"success": False, "error": f"无法创建 OAuth 回调监听器：{created.text}"}
            started = await self._docker_request("POST", f"/containers/{name}/start")
            if started.status_code != 204:
                await self._remove_docker_helper()
                return {"success": False, "error": "1455 端口当前被其他程序占用，请关闭占用后重试"}
            return {"success": True}
        except Exception as exc:
            logger.exception("启动 OAuth 回调辅助容器失败")
            return {"success": False, "error": f"启动 OAuth 回调监听器失败：{exc}"}

    async def _handle_local_callback(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            request_line = (await reader.readline()).decode("latin-1", errors="ignore").strip()
            parts = request_line.split(" ")
            target = parts[1] if len(parts) >= 2 else "/"
            if target.startswith("/auth/callback"):
                location = f"http://localhost:{settings.app_port}{target}"
                response = (
                    "HTTP/1.1 307 Temporary Redirect\r\n"
                    f"Location: {location}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Content-Length: 0\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("latin-1")
            else:
                response = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            writer.write(response)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            asyncio.create_task(self._stop_local_listener())

    async def _start_local_listener(self) -> dict:
        await self._stop_local_listener()
        try:
            self._local_server = await asyncio.start_server(
                self._handle_local_callback, "0.0.0.0", CALLBACK_PORT
            )
            self._local_timeout_task = asyncio.create_task(self._local_timeout())
            return {"success": True}
        except OSError:
            return {"success": False, "error": "1455 端口当前被其他程序占用，请关闭占用后重试"}

    async def _local_timeout(self):
        await asyncio.sleep(CALLBACK_TIMEOUT_SECONDS)
        await self._stop_local_listener()

    async def _stop_local_listener(self):
        if self._local_server:
            self._local_server.close()
            await self._local_server.wait_closed()
            self._local_server = None
        task = self._local_timeout_task
        if task and task is not asyncio.current_task():
            task.cancel()
        self._local_timeout_task = None


oauth_callback_listener = OAuthCallbackListener()
