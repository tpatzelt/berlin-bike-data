"""Runtime configuration loaded from environment variables.

See ``deploy/.bikes.env.example`` for the documented set of variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

DEFAULT_SITE_DIR = "./site-out"
DEFAULT_NEXTBIKE_GBFS_URL = "https://gbfs.nextbike.net/maps/gbfs/v2/nextbike_bn/gbfs.json"
DEFAULT_DOTT_GBFS_URL = "https://gbfs.api.ridedott.com/public/v2/berlin/gbfs.json"

_TRUE_VALUES = {"1", "true", "yes", "on"}


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


def _require(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required but missing or blank")
    return value


def _optional(environ: Mapping[str, str], name: str, default: str) -> str:
    value = environ.get(name, "").strip()
    return value if value else default


def _optional_bool(environ: Mapping[str, str], name: str, default: bool) -> bool:
    value = environ.get(name, "").strip()
    if not value:
        return default
    return value.lower() in _TRUE_VALUES


@dataclass(frozen=True)
class Settings:
    data_dir: str
    site_dir: str
    user_agent: str
    nextbike_gbfs_url: str
    dott_enabled: bool
    dott_gbfs_url: str
    # Impressum / Datenschutz details. Kept out of the repository; the
    # placeholders render when they are unset.
    operator_name: str = "[NAME]"
    operator_address: str = "[ANSCHRIFT]"
    operator_email: str = "[E-MAIL]"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> "Settings":
        return cls(
            data_dir=_require(environ, "BIKES_DATA_DIR"),
            site_dir=_optional(environ, "BIKES_SITE_DIR", DEFAULT_SITE_DIR),
            user_agent=_require(environ, "BIKES_USER_AGENT"),
            nextbike_gbfs_url=_optional(
                environ, "BIKES_NEXTBIKE_GBFS_URL", DEFAULT_NEXTBIKE_GBFS_URL
            ),
            dott_enabled=_optional_bool(environ, "BIKES_DOTT_ENABLED", False),
            dott_gbfs_url=_optional(environ, "BIKES_DOTT_GBFS_URL", DEFAULT_DOTT_GBFS_URL),
            operator_name=_optional(environ, "BIKES_OPERATOR_NAME", "[NAME]"),
            operator_address=_optional(environ, "BIKES_OPERATOR_ADDRESS", "[ANSCHRIFT]"),
            operator_email=_optional(environ, "BIKES_OPERATOR_EMAIL", "[E-MAIL]"),
        )
