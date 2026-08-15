"""Temporary legacy Operations-route bridge for the Marketing host."""

from __future__ import annotations

import os
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

PREFIXES = ("candidates", "data-room", "handler-expenses", "handler-salaries", "company-expenses", "public/slots", "api", "ai/daily-briefing")
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def install_business_compatibility(app: FastAPI) -> None:
    async def forward(request: Request, path: str) -> Response:
        public_base = os.getenv("OPERATIONS_PUBLIC_URL", "").strip().rstrip("/")
        if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
            if not public_base:
                raise HTTPException(status_code=503, detail="Operations public URL is not configured")
            query = f"?{urlencode(list(request.query_params.multi_items()))}" if request.query_params else ""
            return RedirectResponse(f"{public_base}/{path}{query}", status_code=307)
        internal_base = os.getenv("OPERATIONS_INTERNAL_URL", "http://127.0.0.1:8001").rstrip("/")
        token = os.getenv("INTERNAL_SERVICE_TOKEN", "")
        if not token:
                raise HTTPException(status_code=503, detail="Operations compatibility bridge is not configured")
        from core.dashboard_access import operator_profile
        profile = operator_profile(request)
        headers = {
            "X-Internal-Service-Token": token,
            "X-Teleautomation-Role": str(profile.get("role") or ""),
            "X-Teleautomation-Reference": str(profile.get("reference") or ""),
            "X-Teleautomation-Username": str(profile.get("username") or ""),
        }
        for name in ("content-type", "accept", "x-request-id"):
            if request.headers.get(name):
                headers[name] = request.headers[name]
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
            upstream = await client.request(request.method, f"{internal_base}/{path}", params=list(request.query_params.multi_items()), content=await request.body(), headers=headers)
        excluded = {"content-length", "transfer-encoding", "connection", "content-encoding"}
        return Response(upstream.content, status_code=upstream.status_code, headers={k: v for k, v in upstream.headers.items() if k.lower() not in excluded})

    for prefix in PREFIXES:
        async def root(request: Request, _prefix: str = prefix):
            return await forward(request, _prefix)

        async def nested(legacy_path: str, request: Request, _prefix: str = prefix):
            return await forward(request, f"{_prefix}/{legacy_path}")

        app.add_api_route(f"/{prefix}", root, methods=METHODS, include_in_schema=False)
        app.add_api_route(f"/{prefix}/{{legacy_path:path}}", nested, methods=METHODS, include_in_schema=False)
