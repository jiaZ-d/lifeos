"""Shared test fixtures. Tests must be hermetic: LLM calls are forced to the
degraded/template path regardless of the developer's local llm_config.json."""
import pytest


@pytest.fixture(autouse=True)
def force_llm_off(monkeypatch):
    import app.services.llm as llm_mod

    monkeypatch.setattr(llm_mod, "load_llm_config", lambda: {}, raising=False)
    monkeypatch.setattr(llm_mod, "_API_KEY", None, raising=False)
    yield


def pytest_configure(config):
    import warnings

    # P2-5: keep the report readable — drop known noisy warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="aiosqlite")
    warnings.filterwarnings("ignore", message=".*InsecureKeyLength.*")
