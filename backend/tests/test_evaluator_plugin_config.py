"""Server-only plugin policy parsing never imports or installs a plugin."""
import json

import pytest

from app.config import get_evaluator_plugin_config


def test_missing_config_denies_plugins(monkeypatch):
    """No server environment setting means an empty allowlist."""
    monkeypatch.delenv("EVALFORGE_EVALUATOR_PLUGINS", raising=False)
    assert get_evaluator_plugin_config().allowlist == ()


def test_server_config_accepts_id_package_and_version(monkeypatch):
    """Parse only the operator's explicit package-bound allowlist."""
    monkeypatch.setenv("EVALFORGE_EVALUATOR_PLUGINS", json.dumps({"allowlist": [{
        "evaluator_id": "example.quality", "distribution": "example-package",
        "distribution_version": "1.2",
    }]}))
    rule = get_evaluator_plugin_config().allowlist[0]
    assert rule.evaluator_id == "example.quality"
    assert rule.distribution_version == "1.2"


@pytest.mark.parametrize("raw", ["", "{", '{"import_path":"private.module:Plugin"}',
                               '{"allowlist":[{"evaluator_id":"x","distribution":"../x"}]}'])
def test_invalid_server_config_is_safe(monkeypatch, raw):
    """Invalid policies fail closed without rendering environment values in the error."""
    monkeypatch.setenv("EVALFORGE_EVALUATOR_PLUGINS", raw)
    with pytest.raises(RuntimeError, match="Invalid EVALFORGE_EVALUATOR_PLUGINS configuration") as captured:
        get_evaluator_plugin_config()
    assert "private" not in str(captured.value)
