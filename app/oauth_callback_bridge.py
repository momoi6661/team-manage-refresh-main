"""Docker 中一次性使用的 OAuth 回调转发器。"""
import asyncio


async def main():
    completed = asyncio.Event()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        target = "/"
        try:
            request_line = (await reader.readline()).decode("latin-1", errors="ignore").strip()
            parts = request_line.split(" ")
            target = parts[1] if len(parts) >= 2 else "/"
            if target.startswith("/auth/callback"):
                response = (
                    "HTTP/1.1 307 Temporary Redirect\r\n"
                    f"Location: http://localhost:8008{target}\r\n"
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
            if target.startswith("/auth/callback"):
                completed.set()

    server = await asyncio.start_server(handle, "0.0.0.0", 1455)
    async with server:
        try:
            await asyncio.wait_for(completed.wait(), timeout=10 * 60)
        except asyncio.TimeoutError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
