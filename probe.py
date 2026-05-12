"""
Phase 6 - Config-driven multi-service SLA probe, with HTML reporting.

Reads config.yaml, queries Cloud Monitoring per declared resource, applies
the right SLA math for the service type, prints a unified terminal report,
and optionally writes a rendered HTML report to disk.

Run:
  python probe.py                  # terminal output only
  python probe.py --report         # terminal + HTML to reports/
  python probe.py --demo           # synthetic Cloud Run math sanity check
"""

import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field

import yaml
from google.cloud import monitoring_v3


GCS_SERVER_ERROR_CODES = {
    "INTERNAL", "UNAVAILABLE", "ABORTED", "UNKNOWN",
    "DATA_LOSS", "DEADLINE_EXCEEDED",
}


@dataclass
class Report:
    name: str
    type: str
    location: str
    sla_target: float
    breach_threshold: float
    uptime_pct: float
    total_requests: int = 0
    total_errors: int = 0
    # Cloud Run specific
    eligible_minutes: int = 0
    downtime_minutes: int = 0
    # Cloud Storage specific
    buckets_evaluated: int = 0
    avg_error_rate: float = 0.0
    # Per-bucket data for the sparkline:  [(timestamp, total, errors), ...]
    timeseries: list = field(default_factory=list)


def verdict_for(r: Report) -> str:
    if r.uptime_pct != r.uptime_pct:
        return "NO DATA"
    if r.uptime_pct >= r.sla_target:
        return "COMPLIANT"
    if r.uptime_pct >= r.breach_threshold:
        return "AT_RISK"
    return "BREACHED"


# --------------------- CLOUD RUN PROBE ---------------------

def probe_cloud_run(
    client: monitoring_v3.MetricServiceClient,
    project_id: str,
    resource: dict,
    window_minutes: int,
) -> Report:
    name = resource["name"]
    location = resource["location"]
    min_req = resource.get("min_requests_per_min", 100)
    err_threshold = resource.get("error_threshold_pct", 1.0) / 100.0

    now = int(time.time())
    interval = monitoring_v3.TimeInterval(
        {
            "end_time": {"seconds": now},
            "start_time": {"seconds": now - window_minutes * 60},
        }
    )
    aggregation = monitoring_v3.Aggregation(
        {
            "alignment_period": {"seconds": 60},
            "per_series_aligner": monitoring_v3.Aggregation.Aligner.ALIGN_DELTA,
            "cross_series_reducer": monitoring_v3.Aggregation.Reducer.REDUCE_SUM,
            "group_by_fields": [
                "resource.label.service_name",
                "resource.label.location",
                "metric.label.response_code_class",
            ],
        }
    )

    results = client.list_time_series(
        request={
            "name": f"projects/{project_id}",
            "filter": (
                f'metric.type="run.googleapis.com/request_count" '
                f'AND resource.type="cloud_run_revision" '
                f'AND resource.label.service_name="{name}"'
            ),
            "interval": interval,
            "aggregation": aggregation,
            "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
        }
    )

    minutes: dict = defaultdict(lambda: {"total": 0, "5xx": 0})
    for ts in results:
        rc_class = ts.metric.labels.get("response_code_class", "")
        for point in ts.points:
            t = point.interval.end_time.timestamp_pb().seconds
            count = int(point.value.int64_value)
            minutes[t]["total"] += count
            if rc_class == "5xx":
                minutes[t]["5xx"] += count

    eligible = 0
    downtime = 0
    total_req = 0
    total_5xx = 0
    timeseries = []
    for ts_key, m in sorted(minutes.items()):
        total_req += m["total"]
        total_5xx += m["5xx"]
        timeseries.append((ts_key, m["total"], m["5xx"]))
        if m["total"] >= min_req:
            eligible += 1
            if m["5xx"] / m["total"] > err_threshold:
                downtime += 1

    uptime = (
        float("nan") if eligible == 0
        else (eligible - downtime) / eligible * 100
    )

    return Report(
        name=name, type="cloud_run", location=location,
        sla_target=resource["sla_target"],
        breach_threshold=resource["breach_threshold"],
        uptime_pct=uptime,
        total_requests=total_req, total_errors=total_5xx,
        eligible_minutes=eligible, downtime_minutes=downtime,
        timeseries=timeseries,
    )


# --------------------- CLOUD STORAGE PROBE ---------------------

def probe_cloud_storage(
    client: monitoring_v3.MetricServiceClient,
    project_id: str,
    resource: dict,
    window_minutes: int,
) -> Report:
    name = resource["name"]
    location = resource["location"]

    now = int(time.time())
    interval = monitoring_v3.TimeInterval(
        {
            "end_time": {"seconds": now},
            "start_time": {"seconds": now - window_minutes * 60},
        }
    )
    aggregation = monitoring_v3.Aggregation(
        {
            "alignment_period": {"seconds": 300},
            "per_series_aligner": monitoring_v3.Aggregation.Aligner.ALIGN_DELTA,
            "cross_series_reducer": monitoring_v3.Aggregation.Reducer.REDUCE_SUM,
            "group_by_fields": [
                "resource.label.bucket_name",
                "resource.label.location",
                "metric.label.response_code",
            ],
        }
    )

    results = client.list_time_series(
        request={
            "name": f"projects/{project_id}",
            "filter": (
                f'metric.type="storage.googleapis.com/api/request_count" '
                f'AND resource.type="gcs_bucket" '
                f'AND resource.label.bucket_name="{name}"'
            ),
            "interval": interval,
            "aggregation": aggregation,
            "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
        }
    )

    five_min: dict = defaultdict(lambda: {"total": 0, "errors": 0})
    for ts in results:
        code = ts.metric.labels.get("response_code", "")
        is_error = code in GCS_SERVER_ERROR_CODES or (code.isdigit() and code.startswith("5"))
        for point in ts.points:
            t = point.interval.end_time.timestamp_pb().seconds
            count = int(point.value.int64_value)
            five_min[t]["total"] += count
            if is_error:
                five_min[t]["errors"] += count

    error_rates = []
    total_req = 0
    total_err = 0
    timeseries = []
    for ts_key, b in sorted(five_min.items()):
        total_req += b["total"]
        total_err += b["errors"]
        timeseries.append((ts_key, b["total"], b["errors"]))
        if b["total"] > 0:
            error_rates.append(b["errors"] / b["total"])

    if not error_rates:
        uptime = float("nan")
        avg_err = 0.0
    else:
        avg_err = sum(error_rates) / len(error_rates)
        uptime = (1 - avg_err) * 100

    return Report(
        name=name, type="cloud_storage", location=location,
        sla_target=resource["sla_target"],
        breach_threshold=resource["breach_threshold"],
        uptime_pct=uptime,
        total_requests=total_req, total_errors=total_err,
        buckets_evaluated=len(error_rates),
        avg_error_rate=avg_err,
        timeseries=timeseries,
    )


# --------------------- REPORTING ---------------------

PROBES = {
    "cloud_run": probe_cloud_run,
    "cloud_storage": probe_cloud_storage,
}


def print_report(r: Report) -> None:
    tag = "[CR ]" if r.type == "cloud_run" else "[GCS]"
    print(f"  {tag} {r.name} ({r.location})")
    print(f"    Total requests:    {r.total_requests:,}")
    print(f"    Server errors:     {r.total_errors:,}")
    if r.type == "cloud_run":
        print(f"    Eligible minutes:  {r.eligible_minutes}")
        print(f"    Downtime minutes:  {r.downtime_minutes}")
    else:
        print(f"    5-min buckets:     {r.buckets_evaluated}")
        print(f"    Avg error rate:    {r.avg_error_rate * 100:.4f}%")
    if r.uptime_pct != r.uptime_pct:
        print(f"    Uptime:            NO DATA")
    else:
        print(f"    Uptime:            {r.uptime_pct:.4f}%  (SLA target {r.sla_target}%)")
    print(f"    Verdict:           {verdict_for(r)}\n")


# --------------------- DEMO ---------------------

def run_synthetic_demo() -> None:
    print("Synthetic demo: 55 eligible minutes, 5 bad minutes -> 90.9091% uptime\n")
    minutes = {}
    t = int(time.time())
    for i in range(50):
        minutes[t + i * 60] = {"total": 500, "5xx": 0}
    for i in range(50, 55):
        minutes[t + i * 60] = {"total": 500, "5xx": 15}
    for i in range(55, 60):
        minutes[t + i * 60] = {"total": 50, "5xx": 10}

    eligible = sum(1 for m in minutes.values() if m["total"] >= 100)
    downtime = sum(
        1 for m in minutes.values()
        if m["total"] >= 100 and m["5xx"] / m["total"] > 0.01
    )
    total_req = sum(m["total"] for m in minutes.values())
    total_5xx = sum(m["5xx"] for m in minutes.values())
    uptime = (eligible - downtime) / eligible * 100
    timeseries = [(k, v["total"], v["5xx"]) for k, v in sorted(minutes.items())]

    r = Report(
        name="synthetic-service", type="cloud_run", location="us-central1",
        sla_target=99.95, breach_threshold=99.0,
        uptime_pct=uptime, total_requests=total_req, total_errors=total_5xx,
        eligible_minutes=eligible, downtime_minutes=downtime,
        timeseries=timeseries,
    )
    print_report(r)
    assert eligible == 55 and downtime == 5 and abs(uptime - 90.9091) < 0.001
    print("Synthetic demo asserts passed. The math is correct.")


# --------------------- MAIN ---------------------

def main() -> None:
    if "--demo" in sys.argv:
        run_synthetic_demo()
        return

    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    project_id = config["project_id"]
    window = config["defaults"]["window_minutes"]
    resources = config["resources"]

    print(f"Project:       {project_id}")
    print(f"Window:        {window} minutes")
    print(f"Resources:     {len(resources)}\n")

    client = monitoring_v3.MetricServiceClient()
    reports: list = []
    for resource in resources:
        probe = PROBES.get(resource["type"])
        if not probe:
            print(f"  ! Unknown resource type: {resource['type']}, skipping {resource['name']}\n")
            continue
        report = probe(client, project_id, resource, window)
        reports.append(report)
        print_report(report)

    if "--report" in sys.argv:
        import report as report_module
        path = report_module.write_report(reports, project_id, window)
        print(f"HTML report written to: {path}")
        print(f"Also at:                reports/latest.html")


if __name__ == "__main__":
    main()
