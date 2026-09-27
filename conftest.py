import boto3
import pytest
from moto import mock_aws

from devpilot.journal.store import JournalStore, create_journal_table

TEST_TABLE_NAME = "devpilot-journal-test"


@pytest.fixture(autouse=True)
def fake_aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "dummy")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "dummy")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.delenv("AWS_ENDPOINT_URL_DYNAMODB", raising=False)


@pytest.fixture
def dynamodb_resource():
    with mock_aws():
        yield boto3.resource("dynamodb")


@pytest.fixture
def journal_table(dynamodb_resource):
    return create_journal_table(dynamodb_resource, TEST_TABLE_NAME)


@pytest.fixture
def journal_store(journal_table):
    return JournalStore(table=journal_table)
