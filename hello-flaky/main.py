"""
Flaky service for Phase 4B.

Returns HTTP 500 for ERROR_RATE fraction of requests, HTTP 200 otherwise.
ERROR_RATE is set via environment variable at deploy time.

Cloud Run's Python buildpack auto-detects a Flask app named `app` in main.py
and runs it with gunicorn. No Procfile required.
"""

import os
import random

from flask import Flask

app = Flask(__name__)

# At 5%, every minute with normal traffic will breach the 1% SLA threshold,
# so the probe will reliably classify this service as BREACHED.
ERROR_RATE = float(os.environ.get("ERROR_RATE", "0.05"))


@app.route("/")
def root():
    if random.random() < ERROR_RATE:
        return "injected 500 for SLA demo", 500
    return "ok", 200


@app.route("/healthz")
def healthz():
    # Always healthy — used by Cloud Run's own liveness checks
    return "ok", 200


if __name__ == "__main__":
    # For local testing only; Cloud Run uses gunicorn in production
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
