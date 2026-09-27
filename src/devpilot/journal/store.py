from __future__ import annotations

import boto3
from boto3.dynamodb.conditions import Key

from .config import journal_table_name
from .models import JournalEntry


class JournalStore:
    def __init__(self, table=None, table_name: str | None = None, resource=None):
        if table is not None:
            self.table = table
        else:
            resource = resource or boto3.resource("dynamodb")
            self.table = resource.Table(table_name or journal_table_name())

    def record(
        self,
        source: str,
        level: str,
        message: str,
        metadata: dict | None = None,
    ) -> JournalEntry:
        entry = JournalEntry(
            source=source, level=level, message=message, metadata=metadata or {}
        )
        self.table.put_item(Item=entry.to_item())
        return entry

    def recent(self, limit: int = 50) -> list[JournalEntry]:
        response = self.table.query(
            KeyConditionExpression=Key("pk").eq("journal"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [JournalEntry.from_item(item) for item in response["Items"]]


def create_journal_table(resource, table_name: str):
    """Dev/test convenience only.

    From the post-Stage-5 Terraform pass onward, Terraform owns the real
    devpilot-journal table; do not call this against real infrastructure.
    """
    table = resource.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table
