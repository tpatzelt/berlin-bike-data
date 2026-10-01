"""Tests for berlinbikes.config.Settings.from_env."""

import pytest

from berlinbikes.config import (
    DEFAULT_DOTT_GBFS_URL,
    DEFAULT_NEXTBIKE_GBFS_URL,
    DEFAULT_SITE_DIR,
    ConfigError,
    Settings,
)

REQUIRED_ENV = {
    "BIKES_DATA_DIR": "/data/bikes",
    "BIKES_USER_AGENT": "berlin-bike-data/0.1",
}


def test_from_env_with_required_vars_applies_defaults():
    settings = Settings.from_env(REQUIRED_ENV)

    assert settings.data_dir == "/data/bikes"
    assert settings.user_agent == "berlin-bike-data/0.1"
    assert settings.site_dir == DEFAULT_SITE_DIR
    assert settings.nextbike_gbfs_url == DEFAULT_NEXTBIKE_GBFS_URL
    assert settings.dott_enabled is False
    assert settings.dott_gbfs_url == DEFAULT_DOTT_GBFS_URL


def test_from_env_reads_overrides():
    env = {
        **REQUIRED_ENV,
        "BIKES_SITE_DIR": "/srv/site",
        "BIKES_NEXTBIKE_GBFS_URL": "https://example.invalid/gbfs.json",
        "BIKES_DOTT_ENABLED": "true",
        "BIKES_DOTT_GBFS_URL": "https://example.invalid/dott.json",
    }

    settings = Settings.from_env(env)

    assert settings.site_dir == "/srv/site"
    assert settings.nextbike_gbfs_url == "https://example.invalid/gbfs.json"
    assert settings.dott_enabled is True
    assert settings.dott_gbfs_url == "https://example.invalid/dott.json"


def test_missing_data_dir_raises():
    env = {k: v for k, v in REQUIRED_ENV.items() if k != "BIKES_DATA_DIR"}

    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_blank_data_dir_raises():
    env = {**REQUIRED_ENV, "BIKES_DATA_DIR": "   "}

    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_missing_user_agent_raises():
    env = {k: v for k, v in REQUIRED_ENV.items() if k != "BIKES_USER_AGENT"}

    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_blank_user_agent_raises():
    env = {**REQUIRED_ENV, "BIKES_USER_AGENT": ""}

    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_blank_optional_var_falls_back_to_default():
    env = {**REQUIRED_ENV, "BIKES_SITE_DIR": ""}

    settings = Settings.from_env(env)

    assert settings.site_dir == DEFAULT_SITE_DIR


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("", False),
    ],
)
def test_dott_enabled_parsing(value, expected):
    env = {**REQUIRED_ENV, "BIKES_DOTT_ENABLED": value}

    settings = Settings.from_env(env)

    assert settings.dott_enabled is expected


def test_settings_is_frozen():
    settings = Settings.from_env(REQUIRED_ENV)

    with pytest.raises(AttributeError):
        settings.data_dir = "/other"
