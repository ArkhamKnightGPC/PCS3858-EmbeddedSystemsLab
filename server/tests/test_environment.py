import os
from pathlib import Path

import pytest

import main


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    for key in ("MQTT_USERNAME", "MQTT_PASSWORD", "MQTT_BROKER"):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / ".env"
    monkeypatch.setattr(main, "ENV_FILE", path)
    return path


def test_dotenv_loads_from_fixed_path_and_preserves_literal_password(env_file, monkeypatch):
    env_file.write_text("MQTT_USERNAME=test-only\nMQTT_PASSWORD='test ${TOKEN} # literal'\n")
    monkeypatch.chdir(env_file.parent.parent)
    main.load_environment()
    assert os.environ["MQTT_USERNAME"] == "test-only"
    assert os.environ["MQTT_PASSWORD"] == "test ${TOKEN} # literal"


def test_exported_variables_take_precedence(env_file, monkeypatch):
    env_file.write_text("MQTT_BROKER=127.0.0.1\n")
    monkeypatch.setenv("MQTT_BROKER", "10.197.100.243")
    main.load_environment()
    assert os.environ["MQTT_BROKER"] == "10.197.100.243"


def test_template_requires_real_credentials_before_startup(env_file):
    template = Path(main.__file__).resolve().parents[1] / ".env.example"
    env_file.write_text(template.read_text())
    with pytest.raises(RuntimeError, match="server/.env"):
        main.main()
