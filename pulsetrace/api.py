from __future__ import annotations

import ipaddress
import os
import socket
import time
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from pulsetrace.engine import ProbeResult, RollingMetrics, detect_latency_anomaly

app = FastAPI(
    title="PulseTrace API",
    version="1.0.0",
    description="A small, allowlisted API endpoint probe service.",
)

METRICS: dict[str, RollingMetrics] = {}


class ProbeRequest(BaseModel):
    target: str = Field(min_length=8, max_length=2048)
    timeout_seconds: float = Field(default=5.0, ge=0.5, le=10.0)

    @field_validator("target")
    @classmethod
    def require_https_target(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Only absolute HTTPS URLs are supported")
        if parsed.username or parsed.password:
            raise ValueError("Credentials in target URLs are not allowed")
        if parsed.port not in (None, 443):
            raise ValueError("Only the default HTTPS port is allowed")
        return value


def allowed_hosts() -> set[str]:
    raw = os.getenv("PULSETRACE_ALLOWED_HOSTS", "")
    return {host.strip().lower() for host in raw.split(",") if host.strip()}


def validate_public_target(target: str) -> str:
    host = (urlparse(target).hostname or "").lower().rstrip(".")
    if not host or host not in allowed_hosts():
        raise HTTPException(status_code=403, detail="Target host is not in PULSETRACE_ALLOWED_HOSTS")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise HTTPException(status_code=422, detail="Target hostname did not resolve") from exc
    if not addresses:
        raise HTTPException(status_code=422, detail="Target hostname did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise HTTPException(status_code=403, detail="Target resolves to a non-public IP address")
    return host


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "pulsetrace-api"}


@app.post("/api/v1/probe")
async def probe_endpoint(request: ProbeRequest) -> dict[str, object]:
    host = validate_public_target(request.target)
    started = time.perf_counter()
    status_code: int | None = None
    error: str | None = None
    success = False
    try:
        timeout = httpx.Timeout(request.timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.get(request.target, headers={"User-Agent": "PulseTrace-Monitor/1.0"})
            status_code = response.status_code
            success = 200 <= response.status_code < 400
            if not success:
                error = "HTTP " + str(response.status_code)
    except httpx.TimeoutException:
        error = "Request timed out"
    except httpx.HTTPError as exc:
        error = type(exc).__name__
    latency_ms = (time.perf_counter() - started) * 1000
    result = ProbeResult.create(request.target, status_code, latency_ms, success, error)
    history = METRICS.setdefault(host, RollingMetrics(max_samples=250))
    previous = history.summary()["p50_ms"]
    history.add(result)
    summary = history.summary()
    anomaly = detect_latency_anomaly(latency_ms, float(previous)) if previous else False
    return {
        "target": request.target,
        "host": host,
        "status_code": status_code,
        "success": success,
        "latency_ms": result.latency_ms,
        "error": error,
        "anomaly": anomaly,
        "metrics": summary,
        "checked_at": result.checked_at,
    }


@app.get("/api/v1/metrics")
async def get_metrics() -> dict[str, object]:
    return {host: metrics.summary() for host, metrics in METRICS.items()}
