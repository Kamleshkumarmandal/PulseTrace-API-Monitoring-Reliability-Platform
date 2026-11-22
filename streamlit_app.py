from __future__ import annotations

import os
import random
import time
from datetime import datetime, timezone

import httpx
import pandas as pd
import streamlit as st

from pulsetrace.engine import CircuitBreaker, ProbeResult, RollingMetrics, detect_latency_anomaly, percentile

st.set_page_config(page_title="PulseTrace | API Reliability", page_icon="📡", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');
html,body,[class*="css"]{font-family:'DM Sans',sans-serif}
.stApp{background:#f5f7fb;color:#19263c}
[data-testid="stSidebar"]{background:#fff;border-right:1px solid #e7ebf2}
.brand{font:800 25px Manrope;letter-spacing:-1.2px;color:#19263c;margin:4px 0 20px}
.brand span{color:#6759e8}
.hero{background:linear-gradient(112deg,#171d3b,#292c60);border-radius:16px;padding:26px 29px;color:white;margin:7px 0 17px}
.hero .eyebrow{color:#bcb5ff;font-size:9px;font-weight:800;letter-spacing:1.7px;margin-bottom:11px}
.hero h1{font:800 32px Manrope;letter-spacing:-1.6px;color:white;margin:0 0 7px}
.hero p{font-size:12px;line-height:1.65;color:#c9cbe0;max-width:740px;margin:0}
.section-title{font:800 19px Manrope;letter-spacing:-.4px;color:#202c44;margin:9px 0 3px}
.section-sub{font-size:10px;color:#8c97a9;margin-bottom:13px}
div[data-testid="stMetric"]{background:#fff;border:1px solid #e7ebf2;border-radius:11px;padding:13px 15px;box-shadow:0 3px 14px #15213a08}
div[data-testid="stMetricLabel"]{font-size:10px;color:#8792a5}
div[data-testid="stMetricValue"]{font:800 23px Manrope;color:#202c44}
div[data-testid="stMetricDelta"]{font-size:9px}
.service-card{background:white;border:1px solid #e7ebf2;border-radius:11px;padding:13px 15px;margin:0 0 9px}
.service-card strong{font-size:12px;color:#24314a}
.muted{font-size:10px;color:#8e99ab}
.good{color:#279672;background:#e9f8f1;padding:4px 7px;border-radius:18px;font-size:9px;font-weight:700}
.warn{color:#b77c30;background:#fff5e8;padding:4px 7px;border-radius:18px;font-size:9px;font-weight:700}
.bad{color:#c65c50;background:#fff0ee;padding:4px 7px;border-radius:18px;font-size:9px;font-weight:700}
.insight{background:#efedff;border:1px solid #e5e1ff;border-radius:10px;padding:12px 15px;color:#5146bd;font-size:11px;line-height:1.6;margin:10px 0 15px}
.smallcaps{font-size:8px;letter-spacing:1.1px;color:#9ca5b3;font-weight:800}
.stButton>button{border-radius:8px;font-weight:600}
.stButton>button[kind="primary"]{background:#6759e8;border-color:#6759e8}
div[data-testid="stDataFrame"]{border:1px solid #e7ebf2;border-radius:10px;overflow:hidden}
.footer{font-size:9px;color:#9aa4b3;text-align:center;padding:20px 0 6px}
hr{border-color:#e8ecf2}
</style>
""", unsafe_allow_html=True)


def default_services():
    return [
        {"name":"Identity API","url":"https://api.github.com","owner":"Platform","region":"US East","criticality":"Critical","baseline_ms":160,"latency_ms":148,"status_code":200,"checks":1824,"failures":7,"uptime":99.62,"state":"Healthy","last_check":"12 sec ago"},
        {"name":"Catalog Service","url":"https://jsonplaceholder.typicode.com","owner":"Commerce","region":"US West","criticality":"High","baseline_ms":210,"latency_ms":236,"status_code":200,"checks":1432,"failures":18,"uptime":98.74,"state":"Degraded","last_check":"18 sec ago"},
        {"name":"Webhook Gateway","url":"https://httpbin.org","owner":"Integrations","region":"EU Central","criticality":"Critical","baseline_ms":300,"latency_ms":624,"status_code":504,"checks":965,"failures":38,"uptime":96.06,"state":"Incident","last_check":"5 sec ago"},
        {"name":"Docs API","url":"https://example.com","owner":"Developer Experience","region":"Asia Pacific","criticality":"Medium","baseline_ms":180,"latency_ms":126,"status_code":200,"checks":2208,"failures":2,"uptime":99.91,"state":"Healthy","last_check":"21 sec ago"},
    ]


if "services" not in st.session_state:
    st.session_state.services = default_services()
if "events" not in st.session_state:
    st.session_state.events = [
        {"time":"18:04:22","service":"Webhook Gateway","event":"Latency threshold breached","severity":"Critical","detail":"p95 latency crossed 600 ms"},
        {"time":"18:02:10","service":"Catalog Service","event":"Elevated error rate","severity":"Warning","detail":"5xx rate above 1.0%"},
        {"time":"17:58:41","service":"Identity API","event":"Health check passed","severity":"Info","detail":"HTTP 200 · 148 ms"},
        {"time":"17:54:03","service":"Docs API","event":"Health check passed","severity":"Info","detail":"HTTP 200 · 126 ms"},
    ]
if "history" not in st.session_state:
    st.session_state.history = {s["name"]: [] for s in st.session_state.services}
if "breaker" not in st.session_state:
    st.session_state.breaker = {}
if "probe_count" not in st.session_state:
    st.session_state.probe_count = 0

api_url = os.getenv("PULSETRACE_API_URL", "")
try:
    api_url = st.secrets.get("PULSETRACE_API_URL", api_url)
except Exception:
    pass

with st.sidebar:
    st.markdown('<div class="brand">pulse<span>trace</span></div>', unsafe_allow_html=True)
    st.caption("OBSERVABILITY WORKSPACE · DEMO")
    page = st.radio("MONITORING", ["Overview","Services","Incidents","Reliability lab"])
    st.divider()
    st.markdown("**WORKSPACE FILTERS**")
    region = st.selectbox("Region", ["All regions","US East","US West","EU Central","Asia Pacific"])
    st.selectbox("Time window", ["Last 60 minutes","Last 24 hours","Last 7 days"])
    st.divider()
    if st.button("↻ Reset demo telemetry", use_container_width=True):
        st.session_state.services = default_services()
        st.session_state.history = {s["name"]: [] for s in st.session_state.services}
        st.session_state.events = []
        st.session_state.breaker = {}
        st.session_state.probe_count = 0
        st.rerun()
    st.caption("Sample telemetry is simulated. No continuous monitor is running.")
    if api_url:
        st.success("Probe API configured")
    else:
        st.info("Demo mode · API not connected")

services = st.session_state.services
filtered_services = [s for s in services if region == "All regions" or s["region"] == region]
healthy = sum(s["state"] == "Healthy" for s in filtered_services)
degraded = sum(s["state"] == "Degraded" for s in filtered_services)
incidents = sum(s["state"] == "Incident" for s in filtered_services)
avg_uptime = sum(s["uptime"] for s in filtered_services) / max(1,len(filtered_services))
avg_latency = sum(s["latency_ms"] for s in filtered_services) / max(1,len(filtered_services))

st.markdown('<div class="hero"><div class="eyebrow">OBSERVE · UNDERSTAND · RESPOND</div><h1>Know before users notice.</h1><p>Monitor endpoint health, understand latency regressions and rehearse resilient service behaviour. PulseTrace turns raw checks into practical reliability signals.</p></div>', unsafe_allow_html=True)

if page in ("Overview","Services"):
    st.markdown('<div class="section-title">Service health</div><div class="section-sub">A live-looking sample workspace. Use Run demo check to generate new simulated telemetry.</div>', unsafe_allow_html=True)
    a,b,c,d=st.columns(4)
    a.metric("Monitored services",len(filtered_services),"Configured endpoints")
    b.metric("Availability",f"{avg_uptime:.2f}%","Sample rolling window")
    c.metric("Avg. response time",f"{avg_latency:.0f} ms","Across selected services")
    d.metric("Active incidents",incidents,"Needs investigation" if incidents else "No open incidents")

    left,right=st.columns([1.6,1])
    with left:
        st.markdown('<div class="section-title">Endpoint inventory</div>',unsafe_allow_html=True)
        for service in filtered_services:
            badge="good" if service["state"]=="Healthy" else "warn" if service["state"]=="Degraded" else "bad"
            with st.container(border=True):
                x,y,z=st.columns([2.2,1,1])
                x.markdown(f"**{service['name']}**\n\n<span class='muted'>{service['url']}</span>",unsafe_allow_html=True)
                x.caption(f"{service['owner']} · {service['region']} · {service['criticality']}")
                y.metric("Latency",f"{service['latency_ms']} ms",delta=f"{service['latency_ms']-service['baseline_ms']:+.0f} ms vs baseline",delta_color="inverse")
                z.markdown(f"<span class='{badge}'>{service['state']}</span>",unsafe_allow_html=True)
                z.caption(f"HTTP {service['status_code']} · {service['last_check']}")
                p,q=st.columns([1,4])
                if p.button("Run demo check",key="probe-"+service["name"]):
                    base=float(service["baseline_ms"])
                    latency=max(20,random.gauss(base,base*.22))
                    failed=random.random()<(.045 if service["state"]=="Healthy" else .16)
                    code=503 if failed else 200
                    service["latency_ms"]=round(latency,1)
                    service["status_code"]=code
                    service["checks"]+=1
                    if failed:
                        service["failures"]+=1
                    service["uptime"]=round(max(90,100*(1-service["failures"]/max(1,service["checks"]))),2)
                    service["state"]="Incident" if failed or latency>base*2 else "Degraded" if latency>base*1.3 else "Healthy"
                    service["last_check"]="Just now"
                    hist=st.session_state.history.setdefault(service["name"],[])
                    hist.append({"time":datetime.now().strftime("%H:%M:%S"),"latency_ms":latency,"success":not failed})
                    if len(hist)>100: hist.pop(0)
                    severity="Critical" if service["state"]=="Incident" else "Info"
                    st.session_state.events.insert(0,{"time":datetime.now().strftime("%H:%M:%S"),"service":service["name"],"event":"Simulated probe "+("failed" if failed else "passed"),"severity":severity,"detail":f"HTTP {code} · {latency:.0f} ms"})
                    st.session_state.probe_count+=1
                    st.rerun()
        with st.expander("＋ Register endpoint"):
            with st.form("register_endpoint",clear_on_submit=True):
                name=st.text_input("Service name")
                url=st.text_input("HTTPS endpoint URL",placeholder="https://api.example.com/health")
                owner=st.text_input("Owning team",value="Platform")
                criticality=st.selectbox("Criticality",["Critical","High","Medium","Low"])
                added=st.form_submit_button("Add to demo inventory",type="primary")
                if added:
                    if not name.strip() or not url.startswith("https://"):
                        st.error("Enter a service name and an HTTPS URL.")
                    elif any(s["url"]==url.strip() for s in services):
                        st.warning("That URL is already registered.")
                    else:
                        host=url.split("/")[2]
                        st.session_state.services.append({"name":name.strip(),"url":url.strip(),"owner":owner.strip() or "Unassigned","region":"US East","criticality":criticality,"baseline_ms":200,"latency_ms":200,"status_code":200,"checks":0,"failures":0,"uptime":100.0,"state":"Healthy","last_check":"Not checked"})
                        st.session_state.history[name.strip()]=[]
                        st.success("Endpoint added to this browser session.")
                        st.rerun()
    with right:
        st.markdown('<div class="section-title">Latency snapshot</div>',unsafe_allow_html=True)
        chart=pd.DataFrame([{"Service":s["name"],"Latency":s["latency_ms"],"Baseline":s["baseline_ms"]} for s in filtered_services]).set_index("Service")
        st.bar_chart(chart,use_container_width=True)
        st.markdown('<div class="section-title">Reliability signals</div>',unsafe_allow_html=True)
        for s in filtered_services:
            delta=s["latency_ms"]/max(1,s["baseline_ms"])
            if s["state"]=="Incident":
                st.error(f"{s['name']}: investigate current failure or latency regression.")
            elif s["state"]=="Degraded":
                st.warning(f"{s['name']}: latency is {delta:.1f}× its baseline.")
            else:
                st.success(f"{s['name']}: operating within its sample baseline.")
        st.caption(f"{st.session_state.probe_count} simulated checks run in this session.")
    if page=="Overview":
        st.markdown('<div class="section-title">Recent events</div>',unsafe_allow_html=True)
        if st.session_state.events:
            st.dataframe(pd.DataFrame(st.session_state.events[:8]),use_container_width=True,hide_index=True)
        else:
            st.info("No events recorded yet. Run a demo check on a service.")
else:
    if page=="Incidents":
        st.markdown('<div class="section-title">Incident timeline</div><div class="section-sub">Review events generated by the demo probes.</div>',unsafe_allow_html=True)
        incidents_df=pd.DataFrame(st.session_state.events)
        if incidents_df.empty:
            st.success("No incidents in the current session.")
        else:
            st.dataframe(incidents_df,use_container_width=True,hide_index=True)
            st.download_button("⬇ Export event log CSV",incidents_df.to_csv(index=False),"pulsetrace-events.csv","text/csv")
        st.markdown('<div class="section-title">Response checklist</div>',unsafe_allow_html=True)
        for item in ["Confirm scope and affected endpoints","Check recent deploys and dependency changes","Inspect p95/p99 latency and error-rate changes","Mitigate impact and communicate status","Verify recovery before resolving the incident"]:
            st.checkbox(item,key="check-"+item)
    elif page=="Reliability lab":
        st.markdown('<div class="section-title">Reliability engineering lab</div><div class="section-sub">Experiment with resilient-system primitives in a safe, local simulation.</div>',unsafe_allow_html=True)
        tab1,tab2,tab3=st.tabs(["Circuit breaker","Latency anomaly","Percentiles"])
        with tab1:
            st.write("A circuit breaker blocks repeated calls after a failure threshold, then allows one half-open trial after the recovery window.")
            threshold=st.slider("Failure threshold",1,8,3)
            failures=st.slider("Consecutive failures",0,10,4)
            now=time.monotonic()
            from pulsetrace.engine import CircuitBreaker
            breaker=CircuitBreaker(failure_threshold=threshold,recovery_seconds=30)
            for _ in range(failures): breaker.record_failure(now)
            st.metric("Circuit state",breaker.state)
            st.write("New request allowed:",breaker.allow_request(now))
            st.caption("This is a deterministic state-machine demonstration; it does not control production traffic.")
        with tab2:
            x,y=st.columns(2)
            baseline=x.number_input("Baseline latency (ms)",min_value=1.0,value=180.0)
            current=y.number_input("Current latency (ms)",min_value=0.0,value=520.0)
            multiplier=st.slider("Anomaly multiplier",1.2,5.0,2.0,.1)
            if detect_latency_anomaly(current,baseline,multiplier):
                st.error(f"Latency anomaly: {current:.0f} ms exceeds {multiplier:.1f}× baseline.")
            else:
                st.success("No anomaly under the selected threshold.")
        with tab3:
            values=[45,50,53,56,61,63,68,74,81,95,120,160,220,410]
            data=pd.DataFrame({"Response time (ms)":values})
            p50=percentile(values,.5);p95=percentile(values,.95);p99=percentile(values,.99)
            x,y,z=st.columns(3)
            x.metric("p50",f"{p50:.0f} ms");y.metric("p95",f"{p95:.0f} ms");z.metric("p99",f"{p99:.0f} ms")
            st.line_chart(data)
            st.caption("Percentiles are linearly interpolated over this illustrative sample distribution.")

st.divider()
st.markdown('<div class="smallcaps">FASTAPI PROBE SERVICE</div>',unsafe_allow_html=True)
if api_url:
    st.success("A PulseTrace API URL is configured. The real probe action is only available for hosts configured on that service.")
    target=st.text_input("HTTPS URL to probe through your API",placeholder="https://allowlisted.example.com/health")
    timeout=st.slider("Probe timeout (seconds)",1,10,5)
    if st.button("Run real API probe",type="primary",disabled=not target.strip()):
        try:
            response=httpx.post(api_url.rstrip("/")+"/api/v1/probe",json={"target":target,"timeout_seconds":timeout},timeout=15)
            if response.is_success:
                st.json(response.json())
            else:
                st.error(f"Probe API returned {response.status_code}: {response.text[:300]}")
        except httpx.HTTPError as exc:
            st.error(f"Could not reach Probe API: {exc}")
else:
    st.info("Optional: set PULSETRACE_API_URL in Streamlit secrets to enable probes through your separately deployed FastAPI service.")

st.markdown('<div class="footer">PulseTrace · Independent portfolio demo · Sample telemetry is simulated · Real probes require the separately configured, hostname-allowlisted API.</div>',unsafe_allow_html=True)
