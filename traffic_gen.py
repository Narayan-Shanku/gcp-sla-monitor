"""
Phase 4 - Traffic Generator (v2)

Uses `requests` instead of urllib because urllib on macOS / Python 3.13 has
intermittent SSL cert issues against *.run.app. Also actually prints errors
instead of silently counting them as status 0.
"""

import sys
import time
from collections import Counter

import requests


# --------------------- CONFIG ---------------------
URL = "https://hello-stable-895452136067.us-central1.run.app"
DURATION_SECONDS = 300        # 5 minutes
REQUESTS_PER_SECOND = 5
# --------------------------------------------------


def main() -> None:
    if "XXXXXX" in URL:
        sys.exit("Edit URL at the top of this file with your Cloud Run service URL.")

    print(f"Target:   {URL}")
    print(f"Duration: {DURATION_SECONDS}s")
    print(f"Rate:     {REQUESTS_PER_SECOND} req/sec (~{REQUESTS_PER_SECOND*60}/min)")

    # Sanity check — fail fast if the first request doesn't work.
    try:
        r = requests.get(URL, timeout=10)
        print(f"Sanity check: got {r.status_code} from service. Proceeding.\n")
    except Exception as e:
        sys.exit(f"Sanity check failed: {type(e).__name__}: {e}")

    interval = 1.0 / REQUESTS_PER_SECOND
    end_time = time.time() + DURATION_SECONDS
    sent = 0
    statuses: Counter = Counter()
    errors: Counter = Counter()
    start = time.time()
    session = requests.Session()  # reuses TCP connections, faster

    try:
        while time.time() < end_time:
            try:
                r = session.get(URL, timeout=10)
                statuses[r.status_code] += 1
            except Exception as e:
                errors[type(e).__name__] += 1

            sent += 1
            if sent % 50 == 0:
                elapsed = time.time() - start
                rate = sent / elapsed if elapsed else 0
                summary = dict(statuses)
                if errors:
                    summary["errors"] = dict(errors)
                print(f"  sent {sent:>5}  rate {rate:.1f}/s  {summary}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nInterrupted.")

    print(f"\nDone. Sent {sent} requests.")
    print(f"Status breakdown: {dict(statuses)}")
    if errors:
        print(f"Client errors:    {dict(errors)}")
    print("\nWait ~2 minutes for metrics to propagate, then: python probe.py")


if __name__ == "__main__":
    main()
