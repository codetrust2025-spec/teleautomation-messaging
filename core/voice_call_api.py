"""HTTP routes for in-app voice calls (register from server.py)."""



from __future__ import annotations



import json

import logging



from fastapi import Query, Request, WebSocket, WebSocketDisconnect

from fastapi.responses import HTMLResponse, JSONResponse



logger = logging.getLogger(__name__)





def _join_payload(join_token: str) -> dict:

    from services import voice_call_service as svc



    info = svc.get_public_join_info(join_token)

    if not info:

        return {"status": "error", "message": "Invalid or expired call link"}

    if info.get("expired"):

        return {"status": "error", "message": "This call link has expired", "expired": True}

    return {"status": "ok", **info}





def install_voice_call_routes(app) -> None:

    from core import dashboard_auth as auth

    from core import voice_signaling

    from services import voice_call_service as svc



    def _require_user(request: Request) -> str | None:

        return auth.username_from_request_cookies(dict(request.cookies)) or None



    @app.get("/call/join/{join_token}")

    async def call_join_info(join_token: str, request: Request):

        accept = (request.headers.get("accept") or "").lower()

        payload = _join_payload(join_token)

        if "text/html" in accept and payload.get("status") == "ok":

            name = payload.get("lead_name") or "Support team"

            session_id = payload.get("session_id") or ""

            html = f"""<!DOCTYPE html>

<html lang="en"><head>

<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>

<title>Voice call — {name}</title>

<style>body{{font-family:system-ui,sans-serif;max-width:32rem;margin:3rem auto;padding:0 1rem;color:#111}}

.btn{{display:inline-block;margin-top:1rem;padding:.75rem 1.25rem;background:#2563eb;color:#fff;

border-radius:.5rem;text-decoration:none}}</style></head><body>

<h1>Voice call</h1><p>Join the call with <strong>{name}</strong>.</p>

<p id="status">Connecting…</p>

<script>

const token={json.dumps(join_token)};

const wsProto=location.protocol==='https:'?'wss':'ws';

const ws=new WebSocket(`${{wsProto}}://${{location.host}}/voice/ws/${{encodeURIComponent(token)}}`);

ws.onopen=()=>{{document.getElementById('status').textContent='Connected — allow microphone if prompted.';}};

ws.onerror=()=>{{document.getElementById('status').textContent='Could not connect. Ask the team for a new link.';}};

</script></body></html>"""

            return HTMLResponse(html)

        if payload.get("status") != "ok":

            return JSONResponse(payload, status_code=404)

        return payload



    @app.get("/voice/join/{join_token}")

    async def voice_join_alias(join_token: str):

        """Backward-compatible alias for older dashboard bundles."""

        payload = _join_payload(join_token)

        if payload.get("status") != "ok":

            return JSONResponse(payload, status_code=404)

        return payload



    @app.websocket("/voice/ws/{join_token}")

    async def voice_client_ws(websocket: WebSocket, join_token: str):
        from core.voice_call_store import get_session_by_token

        session = get_session_by_token(join_token)

        if not session:

            await websocket.close(code=4404)

            return

        session_id = session.get("id") or ""

        await websocket.accept()

        await voice_signaling.register_peer(session_id, "client", websocket)

        await websocket.send_json({

            "type": "voice",

            "event": "registered",

            "session_id": session_id,

        })

        try:

            while True:

                raw = await websocket.receive_text()

                try:

                    msg = json.loads(raw)

                except json.JSONDecodeError:

                    continue

                if msg.get("type") != "voice" or msg.get("action") != "signal":

                    continue

                signal = msg.get("signal") if isinstance(msg.get("signal"), dict) else {}

                await svc.handle_client_signal(session_id, signal)

        except WebSocketDisconnect:

            pass

        finally:

            await voice_signaling.unregister_peer(session_id, "client", websocket)



    @app.get("/voice/analytics")

    async def voice_analytics(request: Request, days: int = Query(default=30, ge=1, le=365)):

        if not _require_user(request):

            return JSONResponse({"detail": "Authentication required"}, status_code=401)

        try:

            analytics = svc.get_analytics(days=days)

        except Exception as e:

            return {"status": "error", "message": str(e)}

        return {"status": "ok", "analytics": analytics}



    @app.post("/voice/calls/start")

    async def voice_calls_start(request: Request, body: dict | None = None):

        if not _require_user(request):

            return JSONResponse({"detail": "Authentication required"}, status_code=401)

        payload = body or {}

        slot = str(payload.get("account_id") or payload.get("slot") or "").strip()

        user_id = payload.get("user_id")

        if not slot or user_id is None:

            return {"status": "error", "message": "account_id and user_id required"}

        caller = _require_user(request) or ""

        assigned = str(payload.get("assigned_to") or "").strip()

        send_join_dm = bool(payload.get("send_join_dm"))

        call_mode = str(payload.get("call_mode") or "telegram").strip().lower()

        try:

            if call_mode == "telegram":

                result = await svc.start_telegram_native_call(

                    slot,

                    int(user_id),

                    caller=caller,

                    assigned_to=assigned,

                )

            elif call_mode == "hybrid":

                result = await svc.start_hybrid_call(

                    slot,

                    int(user_id),

                    caller=caller,

                    assigned_to=assigned,

                    send_join_dm=send_join_dm,

                )

            else:

                result = await svc.start_voice_call(

                    slot,

                    int(user_id),

                    caller=caller,

                    assigned_to=assigned,

                    send_join_dm=send_join_dm,

                    call_mode=call_mode or "browser",

                )

        except Exception as e:

            return {"status": "error", "message": str(e)}

        return {"status": "ok", **result}



    @app.post("/voice/calls/{session_id}/end")

    async def voice_calls_end(session_id: str, request: Request, body: dict | None = None):

        if not _require_user(request):

            return JSONResponse({"detail": "Authentication required"}, status_code=401)

        payload = body or {}

        try:

            session = await svc.finish_voice_call(

                session_id,

                status=str(payload.get("status") or "ended"),

                outcome=str(payload.get("outcome") or ""),

                notes=str(payload.get("notes") or ""),

                by=_require_user(request) or "operator",

            )

        except Exception as e:

            return {"status": "error", "message": str(e)}

        if not session:

            return {"status": "error", "message": "Session not found"}

        return {"status": "ok", "session": session}



    @app.post("/voice/calls/{session_id}/outcome")

    async def voice_calls_outcome(session_id: str, request: Request, body: dict | None = None):

        if not _require_user(request):

            return JSONResponse({"detail": "Authentication required"}, status_code=401)

        payload = body or {}

        try:

            session = await svc.save_call_outcome(

                session_id,

                outcome=str(payload.get("outcome") or ""),

                notes=str(payload.get("notes") or ""),

            )

        except ValueError as e:

            return {"status": "error", "message": str(e)}

        except Exception as e:

            return {"status": "error", "message": str(e)}

        if not session:

            return {"status": "error", "message": "Session not found"}

        return {"status": "ok", "session": session}
