"""HTTP routes for inbox demo-tool install links."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from core.config import ACCOUNTS


def install_demo_tools_routes(app) -> None:
    from features import demo_tools

    @app.get("/demo-tools")
    async def demo_tools_catalog():
        return demo_tools.catalog_payload()

    @app.post("/inbox/{slot}/send-demo-tools")
    async def inbox_send_demo_tools(slot: str, request: Request, body: dict | None = None):
        if slot not in ACCOUNTS:
            return JSONResponse({"status": "error", "message": "Invalid slot"}, status_code=400)
        payload = body or {}
        try:
            user_id = int(payload.get("user_id"))
        except (TypeError, ValueError):
            return JSONResponse({"status": "error", "message": "user_id required"}, status_code=400)
        if user_id <= 0:
            return JSONResponse({"status": "error", "message": "Invalid user_id"}, status_code=400)

        try:
            result = await demo_tools.send_demo_tools(slot, user_id, sent_by="operator")
        except Exception as exc:
            return JSONResponse(
                {"status": "error", "message": str(exc)[:200]},
                status_code=500,
            )
        if not result.get("ok"):
            reason = result.get("reason") or "send_failed"
            return JSONResponse({"status": "error", "message": reason}, status_code=400)
        return {"status": "ok", **result}
