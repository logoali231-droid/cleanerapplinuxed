"""Shared fixtures for the AI File Cleaner test suite."""
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_bytes(tmp_path):
    """Write arbitrary bytes to a temp file, return its Path."""
    def _write(name, data):
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p
    return _write
