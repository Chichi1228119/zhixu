"""Keep CLI environment mutations inside the test that invokes the CLI."""
import os

import pytest


@pytest.fixture(autouse=True)
def isolate_application_environment():
    def application_key(key):
        return key.startswith(('ZHIXU_', 'RAG_'))
    original = {key: value for key, value in os.environ.items() if application_key(key)}
    yield
    for key in list(os.environ):
        if application_key(key):
            del os.environ[key]
    os.environ.update(original)
