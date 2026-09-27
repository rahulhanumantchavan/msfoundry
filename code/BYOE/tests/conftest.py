"""Offline test setup, scoped exclusively to the BYOE package."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def disable_telemetry(monkeypatch):
    monkeypatch.setenv("PF_DISABLE_TELEMETRY", "true")
    monkeypatch.setenv("AZURE_AI_EVALUATION_DISABLE_TELEMETRY", "true")


@pytest.fixture
def case():
    from byoe.contracts import Case

    return Case(id="one", query="A question", response="The answer is blue.",
                expected={"contains": ["blue"]})


@pytest.fixture
def spec():
    from byoe.contracts import EvaluatorSpec

    return EvaluatorSpec(id="contains", kind="python",
                         config={"entrypoint": "examples.plugins:contains_expected"})