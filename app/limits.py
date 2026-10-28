"""Bound incoming bodies before multipart can spool them to disk."""
from starlette.responses import JSONResponse


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        upload = scope["path"] == "/api/documents"
        maximum = 10 * 1024 * 1024 + 128 * 1024 if upload else 32 * 1024
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
            if declared < 0:
                raise ValueError
        except ValueError:
            return await JSONResponse({"detail": "请求长度无效。"}, status_code=400)(scope, receive, send)
        message = "单个文件不能超过 10 MB。" if upload else "请求内容过大，请缩短输入。"
        if declared > maximum:
            return await JSONResponse({"detail": message}, status_code=413)(scope, receive, send)
        body = bytearray()
        while True:
            incoming = await receive()
            if incoming["type"] == "http.disconnect":
                return
            part = incoming.get("body", b"")
            if len(body) + len(part) > maximum:
                return await JSONResponse({"detail": message}, status_code=413)(scope, receive, send)
            body.extend(part)
            if not incoming.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)
