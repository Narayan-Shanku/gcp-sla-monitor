"""
Phase 5 - Cloud Storage Traffic Generator

Hits the demo bucket with a mix of API operations (upload, list, read) so
the storage.googleapis.com/api/request_count metric has real data for the
probe to query.

Edit BUCKET_NAME, then:  python bucket_traffic_gen.py
"""

import sys
import time
import uuid
from collections import Counter

from google.cloud import storage


# --------------------- CONFIG ---------------------
BUCKET_NAME = "sla-demo-narayan-895452136067"   # <-- edit to your bucket name
DURATION_SECONDS = 300
SLEEP_BETWEEN_OPS = 1.0      # ~3 API calls per cycle, so ~3/sec
# --------------------------------------------------


def main() -> None:
    if "CHANGEME" in BUCKET_NAME:
        sys.exit("Edit BUCKET_NAME at the top of this file.")

    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)

    print(f"Bucket:    gs://{BUCKET_NAME}")
    print(f"Duration:  {DURATION_SECONDS}s")
    print(f"Pattern:   upload + list + read per cycle\n")

    # Sanity check
    try:
        bucket.reload()
        print(f"Sanity check: bucket exists and is accessible.\n")
    except Exception as e:
        sys.exit(f"Sanity check failed: {type(e).__name__}: {e}")

    end = time.time() + DURATION_SECONDS
    start = time.time()
    ops = Counter()
    cycle = 0

    try:
        while time.time() < end:
            obj_name = f"sla-demo/{uuid.uuid4().hex[:8]}.txt"
            blob = bucket.blob(obj_name)

            # 1) upload (PUT)
            try:
                blob.upload_from_string(f"hello from cycle {cycle}")
                ops["upload_ok"] += 1
            except Exception as e:
                ops[f"upload_err_{type(e).__name__}"] += 1

            # 2) list (LIST)
            try:
                list(client.list_blobs(BUCKET_NAME, max_results=5))
                ops["list_ok"] += 1
            except Exception as e:
                ops[f"list_err_{type(e).__name__}"] += 1

            # 3) read metadata (GET)
            try:
                blob.reload()
                ops["read_ok"] += 1
            except Exception as e:
                ops[f"read_err_{type(e).__name__}"] += 1

            cycle += 1
            if cycle % 10 == 0:
                total = sum(ops.values())
                elapsed = time.time() - start
                print(f"  cycle {cycle:>3}  total ops {total:>4}  rate {total/elapsed:.1f}/s  {dict(ops)}")
            time.sleep(SLEEP_BETWEEN_OPS)
    except KeyboardInterrupt:
        print("\nInterrupted.")

    print(f"\nDone. Total ops: {sum(ops.values())}")
    print(f"Breakdown: {dict(ops)}")
    print("\nWait ~2-3 minutes for Cloud Storage metrics to propagate, then: python probe.py")


if __name__ == "__main__":
    main()
