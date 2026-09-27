"""Create the DynamoDB journal table against a local DynamoDB (e.g. DynamoDB Local).

Requires AWS_ENDPOINT_URL_DYNAMODB (and dummy AWS credentials) to be set in the
environment first -- see spec.md section 6.3a.
"""

import boto3

from devpilot.journal.config import journal_table_name
from devpilot.journal.store import create_journal_table


def main() -> None:
    resource = boto3.resource("dynamodb")
    table = create_journal_table(resource, journal_table_name())
    print(f"Created table {table.table_name!r}")


if __name__ == "__main__":
    main()
