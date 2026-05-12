from google.cloud import monitoring_v3
from google.api_core.exceptions import GoogleAPIError, PermissionDenied, NotFound

PROJECT_ID = "project-de927dbf-01c8-460e-be3"

METRICS_TO_CHECK = [
    "run.googleapis.com/request_count",
    "storage.googleapis.com/api/request_count",
]


def describe_metric(client: monitoring_v3.MetricServiceClient, project_id: str, metric_type: str) -> None:
    name = f"projects/{project_id}/metricDescriptors/{metric_type}"

    descriptor = client.get_metric_descriptor(name=name)

    print(f"\n  Metric: {descriptor.type}")
    print(f"  Display name: {descriptor.display_name}")

    # enums are already strings OR ints depending on SDK → just print safely
    print(f"  Kind: {descriptor.metric_kind}")
    print(f"  Value type: {descriptor.value_type}")

    print(f"  Unit: {descriptor.unit or '(none)'}")

    print("  Labels:")
    for label in descriptor.labels:
        print(f"    - {label.key}: {label.description}")


def main():
    print(f"Project: {PROJECT_ID}")
    print(f"Checking {len(METRICS_TO_CHECK)} metric descriptors...\n")

    client = monitoring_v3.MetricServiceClient()

    for metric_type in METRICS_TO_CHECK:
        try:
            describe_metric(client, PROJECT_ID, metric_type)

        except PermissionDenied:
            print(f"\n❌ Permission denied for {metric_type}")
            print("Fix: grant roles/monitoring.viewer")

        except NotFound:
            print(f"\n❌ Metric not found: {metric_type}")
            print("Check API enablement or metric name")

        except GoogleAPIError as e:
            print(f"\n❌ Google API error: {e}")

  


if __name__ == "__main__":
    main()