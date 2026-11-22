# PulseTrace — API Monitoring & Reliability Platform

PulseTrace is an observability portfolio project for monitoring API health, investigating latency changes and demonstrating reliability engineering concepts.

The repository provides a **Streamlit demo dashboard** for a quick public portfolio link and a separate **FastAPI probe service** for allowlisted HTTPS checks.

## Demo dashboard features

🚀live demo link
https://pulsetrace-api-monitoring-reliability-platform-xheakdbvuyuzxbt.streamlit.app/

- Service inventory with ownership, region, criticality and health state
- Availability, response-time and incident summary cards
- Simulated endpoint checks that update the current session's telemetry
- Latency snapshot and service health signals
- Incident/event timeline and CSV export
- Register a service endpoint in the current demo session
- Reliability lab for circuit breakers, latency anomaly thresholds and p50/p95/p99 percentiles
- Optional connection to a separately deployed FastAPI probe service

## Important: demo telemetry vs. real monitoring

The Streamlit dashboard uses **simulated sample telemetry**. It does not run continuous background checks, and simulated endpoint state resets when the app session restarts. No production SLA or uptime claim should be inferred from the sample charts.

The FastAPI service offers real, on-demand HTTPS probes. To reduce SSRF risk, it only probes exact hostnames listed in `PULSETRACE_ALLOWED_HOSTS`, rejects credentials and non-default ports, resolves hostnames and rejects non-public IP addresses, and does not follow redirects. Do not expose an unrestricted probe service publicly. For production, use a network egress policy, rate limiting, authentication, pinned DNS resolution, audit logging and a dedicated worker.

## Tech stack

- Python 3.11+
- Streamlit dashboard
- FastAPI + Pydantic + HTTPX probe API
- Pandas for telemetry presentation
- In-memory rolling metrics and reliability primitives
- unittest test suite
- Docker for the API service

## Run the Streamlit demo locally

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run streamlit_app.py
```

macOS / Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy the demo to Streamlit Community Cloud

1. Sign in at https://share.streamlit.io with GitHub.
2. Choose **Create app** and select the existing repository.
3. Repository: `Kamleshkumarmandal/PulseTrace-API-Monitoring-Reliability-Platform`.
4. Branch: `main`.
5. Main file path: `streamlit_app.py`.
6. Click **Deploy**.

Streamlit reads dependencies from the root `requirements.txt` and theme settings from `.streamlit/config.toml`.

## Run the FastAPI probe service locally

```bash
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
$env:PULSETRACE_ALLOWED_HOSTS="api.github.com,jsonplaceholder.typicode.com,httpbin.org,example.com"
uvicorn pulsetrace.api:app --reload
```

macOS / Linux:

```bash
export PULSETRACE_ALLOWED_HOSTS="api.github.com,jsonplaceholder.typicode.com,httpbin.org,example.com"
uvicorn pulsetrace.api:app --reload
```

- Health check: `GET http://localhost:8000/health`
- Probe endpoint: `POST http://localhost:8000/api/v1/probe`
- Metrics summary: `GET http://localhost:8000/api/v1/metrics`
- Interactive API docs: `http://localhost:8000/docs`

Example request:

```json
{
  "target": "https://api.github.com",
  "timeout_seconds": 5
}
```

The probe service has an in-memory rolling window and loses metrics on restart. The allowlist is intentionally configured by the operator; leave it empty to disable outbound probes.

To connect a separately deployed probe service to Streamlit, set `PULSETRACE_API_URL` in Streamlit app secrets to its base URL. The service must have its own `PULSETRACE_ALLOWED_HOSTS` setting.

## Reliability concepts demonstrated

- Percentile latency calculations with linear interpolation
- Fixed-size rolling metric windows
- Availability and error-rate calculations
- Circuit breaker state machine: CLOSED → OPEN → HALF_OPEN
- Latency regression threshold checks
- Explicit request timeouts and no automatic redirect following
- Host allowlisting and basic public-IP validation

## Run tests

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## Project structure

```text
pulsetrace/
  __init__.py
  engine.py
  api.py
streamlit_app.py
tests/
  test_engine.py
  test_api.py
  test_streamlit_smoke.py
requirements.txt
Dockerfile
```

## Roadmap

- [ ] Persistent metric storage (PostgreSQL / TimescaleDB)
- [ ] Redis-backed scheduling and distributed probe workers
- [ ] Authenticated workspaces and role-based access
- [ ] Scheduled monitoring with per-endpoint intervals
- [ ] Alert policies, notification channels and incident acknowledgement
- [ ] OpenTelemetry trace ingestion and correlation
- [ ] Multi-region probes and SLO / error-budget reporting
- [ ] Load testing, security review and operational runbooks

## License

MIT. See [LICENSE](LICENSE).
