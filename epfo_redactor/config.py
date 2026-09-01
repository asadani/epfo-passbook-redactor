"""Optional YAML config, for runs you repeat.

Precedence, lowest to highest: field defaults, the named profile, the config
file, then command-line flags. Anything absent from a layer is inherited.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_FILENAME = "epfo-redact.yaml"

KNOWN_KEYS = {
    "profile",
    "mask",
    "no-mask",
    "keep-chars",
    "keep-rows",
    "style",
    "field-style",
    "group-by",
    "merge",
    "out",
}


class ConfigError(ValueError):
    """Raised for a malformed config file."""


@dataclass
class Config:
    profile: str | None = None
    mask: tuple[str, ...] = ()
    no_mask: tuple[str, ...] = ()
    keep_chars: dict[str, int] = field(default_factory=dict)
    keep_rows: tuple[str, ...] = ()
    styles: dict[str, str] = field(default_factory=dict)
    group_by: str | None = None
    merge: bool | None = None
    out: str | None = None


def _as_tuple(value, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    raise ConfigError(f"{key!r} must be a string or a list")


def discover(explicit: str | None, cwd: Path | None = None) -> Path | None:
    """Explicit path if given, else ./epfo-redact.yaml if it exists."""
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        return path
    candidate = (cwd or Path.cwd()) / DEFAULT_FILENAME
    return candidate if candidate.is_file() else None


def load(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping")

    unknown = set(raw) - KNOWN_KEYS
    if unknown:
        raise ConfigError(
            f"{path}: unknown key(s) {', '.join(sorted(unknown))}; "
            f"valid keys are {', '.join(sorted(KNOWN_KEYS))}"
        )

    keep_chars = raw.get("keep-chars") or {}
    if not isinstance(keep_chars, dict):
        raise ConfigError(f"{path}: 'keep-chars' must be a mapping of field: count")

    styles: dict[str, str] = {}
    if raw.get("style"):
        styles["all"] = str(raw["style"])
    field_style = raw.get("field-style") or {}
    if not isinstance(field_style, dict):
        raise ConfigError(f"{path}: 'field-style' must be a mapping of field: style")
    styles.update({str(k): str(v) for k, v in field_style.items()})

    return Config(
        profile=raw.get("profile"),
        mask=_as_tuple(raw.get("mask"), "mask"),
        no_mask=_as_tuple(raw.get("no-mask"), "no-mask"),
        keep_chars={str(k): int(v) for k, v in keep_chars.items()},
        keep_rows=_as_tuple(raw.get("keep-rows"), "keep-rows"),
        styles=styles,
        group_by=raw.get("group-by"),
        merge=raw.get("merge"),
        out=raw.get("out"),
    )
