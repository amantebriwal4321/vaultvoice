import os

os.environ["QDRANT_IN_MEMORY"] = "1"
os.environ["EMBEDDER"] = "hash"
os.environ["AUDIT_PATH"] = ""
os.environ["VAULT_FORCE_LOCAL"] = "1"
os.environ["LYZR_API_KEY"] = ""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client
