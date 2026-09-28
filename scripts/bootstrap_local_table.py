"""Create the DynamoDB journal table against a local DynamoDB (e.g. DynamoDB Local).

Requires AWS_ENDPOINT_URL_DYNAMODB (and dummy AWS credentials) to be set in the
environment first -- see spec.md section 6.3a. Retries on connection failure
since in docker-compose this can start before DynamoDB Local is accepting
connections yet.
"""

import sys
import time

import boto3
import botocore.exceptions

from devpilot.journal.config import journal_table_name
from devpilot.journal.store import create_journal_table

MAX_ATTEMPTS = 10
RETRY_DELAY_SECONDS = 2


def main() -> None:
    resource = boto3.resource("dynamodb")
    table_name = journal_table_name()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            table = create_journal_table(resource, table_name)
            print(f"Created table {table.table_name!r}")
            return
        except botocore.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] == "ResourceInUseException":
                print(f"Table {table_name!r} already exists -- nothing to do")
                return
            raise
        except (botocore.exceptions.EndpointConnectionError, botocore.exceptions.ConnectionError):
            if attempt == MAX_ATTEMPTS:
                raise
            print(f"DynamoDB not reachable yet (attempt {attempt}/{MAX_ATTEMPTS}), retrying...")
            time.sleep(RETRY_DELAY_SECONDS)

    sys.exit(f"Could not create table {table_name!r} after {MAX_ATTEMPTS} attempts")


if __name__ == "__main__":
    main()
