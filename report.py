"""
Phase 6 - HTML report renderer.

Takes a list of Report objects produced by probe.py and writes a self-contained
HTML page with:
  - Header (project, timestamp, window)
  - Summary stats (compliant / at-risk / breached counts)
  - One card per resource with metrics + inline SVG sparkline

No external dependencies. The output file is portable and can be opened in
any browser, attached to a PR, or uploaded to GCS for the team.
"""

import os
from datetime import datetime, timezone


CSS = """
  :root {
    --bg: #f8fafc;
    --card-bg: #ffffff;
    --text: #0f172a;
    --muted: #64748b;
    --border: #e2e8f0;
    --compliant: #16a34a;
    --compliant-bg: #dcfce7;
    --at-risk: #d97706;
    --at-risk-bg: #fef3c7;
    --breached: #dc2626;
    --breached-bg: #fee2e2;
    --no-data: #64748b;
    --no-data-bg: #f1f5f9;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.5;
  }
  .container { max-width: 960px; margin: 0 auto; padding: 32px 24px; }
  header { margin-bottom: 24px; }
  h1 { margin: 0 0 8px 0; font-size: 24px; font-weight: 600; }
  .meta { color: var(--muted); font-size: 13px; }
  .meta code {
    background: var(--card-bg);
    padding: 2px 6px;
    border-radius: 4px;
    border: 1px solid var(--border);
    font-size: 12px;
  }
  .summary {
    display: flex;
    gap: 12px;
    margin-bottom: 24px;
  }
  .stat {
    flex: 1;
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    text-align: center;
  }
  .stat-value { font-size: 28px; font-weight: 600; }
  .stat-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--muted);
    margin-top: 4px;
  }
  .stat.compliant .stat-value { color: var(--compliant); }
  .stat.at-risk .stat-value { color: var(--at-risk); }
  .stat.breached .stat-value { color: var(--breached); }
  .stat.no-data .stat-value { color: var(--no-data); }
  .card {
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 16px;
  }
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
    flex-wrap: wrap;
    gap: 12px;
  }
  .card-title h2 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }
  .type-tag {
    display: inline-block;
    background: var(--no-data-bg);
    color: var(--muted);
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-family: ui-monospace, SFMono-Regular, monospace;
    margin-right: 8px;
    vertical-align: middle;
  }
  .location {
    color: var(--muted);
    font-weight: 400;
    font-size: 13px;
    margin-left: 8px;
  }
  .verdict {
    padding: 4px 12px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.3px;
  }
  .verdict.compliant { background: var(--compliant-bg); color: var(--compliant); }
  .verdict.at-risk { background: var(--at-risk-bg); color: var(--at-risk); }
  .verdict.breached { background: var(--breached-bg); color: var(--breached); }
  .verdict.no-data { background: var(--no-data-bg); color: var(--no-data); }
  .metrics {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 16px;
    margin-bottom: 16px;
  }
  .metric { }
  .metric-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--muted);
    margin-bottom: 4px;
  }
  .metric-value {
    font-size: 18px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .metric-sub {
    font-size: 12px;
    color: var(--muted);
    margin-top: 2px;
  }
  .uptime-value.compliant { color: var(--compliant); }
  .uptime-value.at-risk { color: var(--at-risk); }
  .uptime-value.breached { color: var(--breached); }
  .sparkline-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }
  .sparkline-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--muted);
  }
  .sparkline-legend {
    font-size: 11px;
    color: var(--muted);
  }
  .sparkline-legend .sw {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 1px;
    margin-right: 4px;
    vertical-align: middle;
  }
  .sw.ok { background: #94a3b8; }
  .sw.err { background: var(--breached); }
  footer {
    margin-top: 32px;
    text-align: center;
    color: var(--muted);
    font-size: 12px;
  }
"""


def _verdict_class(verdict: str) -> str:
    return verdict.lower().replace("_", "-").replace(" ", "-")


def _render_sparkline(timeseries: list) -> str:
    """SVG bar sparkline: gray bars for clean buckets, red for buckets with errors."""
    if not timeseries:
        return '<span class="sparkline-legend">No data</span>'

    sorted_ts = sorted(timeseries, key=lambda x: x[0])
    max_total = max((t for _, t, _ in sorted_ts), default=1) or 1

    width, height = 280, 36
    n = len(sorted_ts)
    bar_w = width / n

    bars = []
    for i, (_, total, errors) in enumerate(sorted_ts):
        bar_h = (total / max_total) * height
        x = i * bar_w
        y = height - bar_h
        color = "#dc2626" if errors > 0 else "#94a3b8"
        bars.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" '
            f'width="{max(bar_w - 1, 1):.2f}" height="{bar_h:.2f}" fill="{color}"/>'
        )

    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg">{"".join(bars)}</svg>'
    )


def _render_card(report) -> str:
    """One card for one Report."""
    from probe import verdict_for  # late import to avoid circular dep on module load

    verdict = verdict_for(report)
    verdict_cls = _verdict_class(verdict)
    type_tag = "CR" if report.type == "cloud_run" else "GCS"

    if report.uptime_pct != report.uptime_pct:
        uptime_str = "—"
        uptime_sub = "No eligible data"
    else:
        uptime_str = f"{report.uptime_pct:.4f}%"
        uptime_sub = f"SLA target {report.sla_target}%"

    # Type-specific metric tiles
    type_specific = ""
    if report.type == "cloud_run":
        type_specific = f"""
          <div class="metric">
            <div class="metric-label">Eligible minutes</div>
            <div class="metric-value">{report.eligible_minutes}</div>
            <div class="metric-sub">had ≥ 100 req/min</div>
          </div>
          <div class="metric">
            <div class="metric-label">Downtime minutes</div>
            <div class="metric-value">{report.downtime_minutes}</div>
            <div class="metric-sub">&gt; 1% errors in minute</div>
          </div>
        """
    else:
        type_specific = f"""
          <div class="metric">
            <div class="metric-label">5-min buckets</div>
            <div class="metric-value">{report.buckets_evaluated}</div>
            <div class="metric-sub">averaged for uptime</div>
          </div>
          <div class="metric">
            <div class="metric-label">Avg error rate</div>
            <div class="metric-value">{report.avg_error_rate * 100:.4f}%</div>
            <div class="metric-sub">across buckets</div>
          </div>
        """

    return f"""
    <div class="card">
      <div class="card-header">
        <div class="card-title">
          <h2>
            <span class="type-tag">{type_tag}</span>{report.name}<span class="location">{report.location}</span>
          </h2>
        </div>
        <span class="verdict {verdict_cls}">{verdict}</span>
      </div>
      <div class="metrics">
        <div class="metric">
          <div class="metric-label">Uptime</div>
          <div class="metric-value uptime-value {verdict_cls}">{uptime_str}</div>
          <div class="metric-sub">{uptime_sub}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Total requests</div>
          <div class="metric-value">{report.total_requests:,}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Server errors</div>
          <div class="metric-value">{report.total_errors:,}</div>
        </div>
        {type_specific}
      </div>
      <div class="sparkline-row">
        <div>
          <div class="sparkline-label">Traffic over window</div>
          {_render_sparkline(report.timeseries)}
        </div>
        <div class="sparkline-legend">
          <span class="sw ok"></span> clean bucket &nbsp;
          <span class="sw err"></span> bucket with errors
        </div>
      </div>
    </div>
    """


def render_html(reports: list, project_id: str, window_minutes: int) -> str:
    from probe import verdict_for

    counts = {"COMPLIANT": 0, "AT_RISK": 0, "BREACHED": 0, "NO DATA": 0}
    for r in reports:
        counts[verdict_for(r)] += 1

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    summary = f"""
      <div class="summary">
        <div class="stat compliant">
          <div class="stat-value">{counts['COMPLIANT']}</div>
          <div class="stat-label">Compliant</div>
        </div>
        <div class="stat at-risk">
          <div class="stat-value">{counts['AT_RISK']}</div>
          <div class="stat-label">At Risk</div>
        </div>
        <div class="stat breached">
          <div class="stat-value">{counts['BREACHED']}</div>
          <div class="stat-label">Breached</div>
        </div>
        <div class="stat no-data">
          <div class="stat-value">{counts['NO DATA']}</div>
          <div class="stat-label">No Data</div>
        </div>
      </div>
    """

    cards = "\n".join(_render_card(r) for r in reports)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SLA Compliance Report — {project_id}</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="container">
    <header>
      <h1>SLA Compliance Report</h1>
      <div class="meta">
        Project <code>{project_id}</code> &nbsp;·&nbsp;
        Generated {now} &nbsp;·&nbsp;
        Window {window_minutes} minutes
      </div>
    </header>
    {summary}
    <main>
      {cards}
    </main>
    <footer>
      gcp-sla-monitor
    </footer>
  </div>
</body>
</html>
"""


def write_report(
    reports: list,
    project_id: str,
    window_minutes: int,
    output_dir: str = "reports",
) -> str:
    """Render and write to disk. Returns the path."""
    os.makedirs(output_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    path = os.path.join(output_dir, f"sla-report-{stamp}.html")
    html = render_html(reports, project_id, window_minutes)
    with open(path, "w") as f:
        f.write(html)
    # Also write/overwrite a stable "latest" copy for easy linking
    latest = os.path.join(output_dir, "latest.html")
    with open(latest, "w") as f:
        f.write(html)
    return path
