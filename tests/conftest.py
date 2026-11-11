"""Shared fixtures: synthetic .xls files are written once per test session into a temp folder."""

from pathlib import Path

import pytest

from tests.fixtures.make_synthetic import write_all


@pytest.fixture(scope="session")
def synthetic_files(tmp_path_factory) -> dict[str, Path]:
    return write_all(tmp_path_factory.mktemp("fixtures"))
