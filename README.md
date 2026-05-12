# gcp-sla-monitor

A small, self-contained Python tool that monitors SLA compliance for Cloud
Run and Cloud Storage in a GCP project. Queries Cloud Monitoring directly,
applies the math each service's actual SLA contract defines, and renders a
color-coded HTML report. Driven by a single YAML config — adding a resource
is one entry, no code changes.

See [`WRITEUP.md`](./WRITEUP.md) for the full design discussion: how I read
the SLAs, why Cloud Run and Cloud Storage use different math, modeling gaps
I'm aware of, and how the tool would be wired up for a team.

---

## What it does in 30 seconds

```bash
$ python probe.py

Project:       your-project-id
Window:        60 minutes
Resources:     2

  [CR ] hello-stable (us-central1)
    Total requests:    2,304
    Server errors:     0
    Eligible minutes:  10
    Downtime minutes:  0
    Uptime:            100.0000%  (SLA target 99.95%)
    Verdict:           COMPLIANT

  [GCS] sla-demo-bucket (us-central1)
    Total requests:    641
    Server errors:     0
    5-min buckets:     3
    Avg error rate:    0.0000%
    Uptime:            100.0000%  (SLA target 99.9%)
    Verdict:           COMPLIANT
```

Add `--report` to also write an HTML version to `reports/latest.html`.

---

## Prerequisites

- A GCP project (free tier is fine)
- `gcloud` CLI installed and authenticated
- Python 3.10 or newer
- Basic IAM permissions on the project: `roles/monitoring.viewer` at minimum.
  Project Owner or Editor (the default for projects you create yourself) is
  more than sufficient.

---

## Quick start (replicate the demo end-to-end)

The full setup, from zero to seeing both services COMPLIANT in a single
report, takes about 15 minutes.

### 1. Clone and install

```bash
git clone https://github.com/Narayan-shanku/gcp-sla-monitor.git
cd gcp-sla-monitor

python3 -m venv .venv
source .venv/bin/activate            # macOS/Linux
# .venv\Scripts\activate              # Windows

pip install -r requirements.txt
```

### 2. Point gcloud at your project and authenticate

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

The last command silences a warning that otherwise escalates to errors on
complex queries.

### 3. Enable the APIs

```bash
gcloud services enable \
  monitoring.googleapis.com \
  run.googleapis.com \
  storage.googleapis.com
```

### 4. Verify everything is wired up

```bash
python verify_setup.py
```

You should see two metric descriptor blocks printed — one for Cloud Run, one
for Cloud Storage. If anything fails, the script tells you which prerequisite
needs attention.

### 5. Configure what to monitor

```bash
cp config.yaml.example config.yaml
```

Open `config.yaml` and edit:

- `project_id` — your GCP project ID
- The Cloud Run resource `name` — set to the service you'll deploy in step 6
- The Cloud Storage resource `name` — set to the bucket you'll create in step 7

### 6. Deploy a Cloud Run service to monitor

```bash
gcloud run deploy hello-stable \
  --image=us-docker.pkg.dev/cloudrun/container/hello \
  --region=us-central1 \
  --allow-unauthenticated
```

Copy the printed Service URL — you'll paste it into `traffic_gen.py`.

### 7. Create a Cloud Storage bucket to monitor

```bash
# Bucket names must be globally unique; appending the project number is a
# common trick to guarantee uniqueness.
PROJECT_NUM=$(gcloud projects describe YOUR_PROJECT_ID --format='value(projectNumber)')
gcloud storage buckets create gs://sla-demo-${PROJECT_NUM} \
  --location=us-central1 \
  --uniform-bucket-level-access
```

Update `BUCKET_NAME` at the top of `bucket_traffic_gen.py` with the bucket
name (without the `gs://` prefix). Also update the `name` field for the
Cloud Storage resource in `config.yaml`.

### 8. Generate traffic on both services

Open `traffic_gen.py` and set the `URL` at the top to your Cloud Run service
URL from step 6, then:

```bash
python traffic_gen.py            # ~5 minutes of Cloud Run traffic
python bucket_traffic_gen.py     # ~5 minutes of Cloud Storage traffic
```

Each script generates enough requests to clear the SLA's eligibility floor.

### 9. Run the probe

Wait about 2 minutes for Cloud Monitoring to ingest the metrics, then:

```bash
python probe.py --report
```

You should see the same kind of output shown at the top of this README, plus
a generated HTML file at `reports/latest.html`. Open it in any browser.

### 10. Sanity-check the math (optional but recommended)

```bash
python probe.py --demo
```

Runs the SLA math against synthetic input with assert statements. Useful
for verifying the math works as expected before trusting the live numbers.

---

## Configuration

The whole tool is driven by `config.yaml`. Each entry under `resources` is
one thing to monitor. To add a new resource, add an entry — no code changes
needed (provided the service type is supported; currently `cloud_run` and
`cloud_storage`).

```yaml
project_id: your-project-id

defaults:
  window_minutes: 60      # how far back to look on each run

resources:
  - name: hello-stable
    type: cloud_run
    location: us-central1
    sla_target: 99.95     # Cloud Run non-GPU standard regions
    breach_threshold: 99.0
    min_requests_per_min: 100   # SLA's volume floor for error rate to count
    error_threshold_pct: 1.0    # > this % errors in a minute = downtime minute

  - name: my-bucket
    type: cloud_storage
    location: us-central1
    sla_target: 99.9      # Standard storage in a regional location
    breach_threshold: 99.0
```

### SLA target reference

The promised uptimes aren't uniform; pick the right target for each
resource:

| Service / class / location | SLA target |
|---|---|
| Cloud Run non-GPU, standard regions | 99.95% |
| Cloud Run non-GPU, Mexico / Stockholm | 99.9% |
| Cloud Storage Standard, multi/dual-region | 99.95% |
| Cloud Storage Standard regional, OR Nearline/Coldline/Archive multi/dual-region | 99.9% |
| Cloud Storage Nearline/Coldline/Archive regional | 99.0% |

---

## Repository structure

```
gcp-sla-monitor/
├── README.md                 # you are here
├── WRITEUP.md                # full design discussion
├── requirements.txt          # Python dependencies
├── config.yaml.example       # template — copy to config.yaml and edit
├── probe.py                  # main entry: query + dispatch + math
├── report.py                 # HTML rendering
├── verify_setup.py           # auth + API enablement smoke test
├── traffic_gen.py            # Cloud Run traffic generator
├── bucket_traffic_gen.py     # Cloud Storage traffic generator
└── reports/                  # rendered HTML reports land here
```

---

## How it works at a glance

```
                       ┌──────────────────┐
                       │   config.yaml    │
                       │  resources +     │
                       │   SLA targets    │
                       └────────┬─────────┘
                                │
                                ▼
   ┌──────────────────┐  ┌──────────────┐  ┌──────────────────────┐
   │ Cloud Monitoring │◄─┤  probe.py    │─►│      report.py       │
   │ API              │  │  dispatch +  │  │   HTML rendering     │
   │ (list_time_      │  │  per-type    │  │   SVG sparklines     │
   │  series)         │  │  SLA math    │  │                      │
   └──────────────────┘  └──────┬───────┘  └──────────┬───────────┘
                                │                     │
                                ▼                     ▼
                        terminal output      reports/sla-report-*.html
```

Cloud Run and Cloud Storage have different SLA contract shapes — Cloud Run
counts bad minutes (per-minute error rate above 1%), Cloud Storage averages
5-minute error rates across the window. `probe.py` honors both by
dispatching to a per-type handler (`probe_cloud_run` / `probe_cloud_storage`),
each with its own aggregation and math.

See [`WRITEUP.md`](./WRITEUP.md) for the full breakdown.

---

## Cleaning up

If you want to tear down the demo resources after replication:

```bash
gcloud run services delete hello-stable --region=us-central1 --quiet
gcloud storage rm -r gs://sla-demo-${PROJECT_NUM}
```

The Cloud Monitoring API is free at the volumes used here, but you may want
to disable the APIs if you won't keep using them.

---

## License

MIT (see [LICENSE](./LICENSE) if present, otherwise free to reuse for any
purpose).
