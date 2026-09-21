from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    name: str
    root: Path
    patterns: tuple[str, ...]
    older_than_days: int
    max_depth: int


@dataclass(frozen=True)
class Config:
    targets: tuple[Target, ...]
    forbidden_roots: tuple[Path, ...]
    max_deletes_per_run: int
    trash_dir: Path | None
    trash_retention_days: int
    workers: int


_REQUIRED_TARGET_FIELDS = ('name', 'root', 'patterns')
_DEFAULTS_FALLBACK = {
    'older_than_days': 30,
    'max_deletes_per_run': 10000,
    'trash_dir': None,
    'trash_retention_days': 7,
    'workers': 4,
}


def load(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    if not isinstance(raw, dict):
        raise ConfigError('config raiz debe ser un mapping')

    defaults = {**_DEFAULTS_FALLBACK, **(raw.get('defaults') or {})}
    raw_targets = raw.get('targets') or []
    if not raw_targets:
        raise ConfigError('config no define ningun target')

    seen_names: set[str] = set()
    targets: list[Target] = []
    for i, t in enumerate(raw_targets):
        for f in _REQUIRED_TARGET_FIELDS:
            if f not in t:
                raise ConfigError(f'target #{i} sin campo requerido: {f}')
        if t['name'] in seen_names:
            raise ConfigError(f'nombre de target duplicado: {t["name"]}')
        seen_names.add(t['name'])

        patterns = tuple(t['patterns'])
        if not patterns:
            raise ConfigError(f'target {t["name"]} sin patterns')

        older = int(t.get('older_than_days', defaults['older_than_days']))
        if older < 0:
            raise ConfigError(f'target {t["name"]}: older_than_days negativo')

        max_depth = int(t.get('max_depth', 5))
        if max_depth < 0:
            raise ConfigError(f'target {t["name"]}: max_depth negativo')

        targets.append(Target(
            name=t['name'],
            root=Path(t['root']),
            patterns=patterns,
            older_than_days=older,
            max_depth=max_depth,
        ))

    forbidden = tuple(Path(p) for p in (raw.get('forbidden_roots') or []))

    trash_dir_raw = defaults.get('trash_dir')
    trash_dir = Path(trash_dir_raw) if trash_dir_raw else None

    return Config(
        targets=tuple(targets),
        forbidden_roots=forbidden,
        max_deletes_per_run=int(defaults['max_deletes_per_run']),
        trash_dir=trash_dir,
        trash_retention_days=int(defaults['trash_retention_days']),
        workers=int(defaults['workers']),
    )
