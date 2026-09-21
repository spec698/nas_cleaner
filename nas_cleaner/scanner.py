"""Enumeracion eficiente de candidatos a borrar.

Usa os.scandir (no os.walk) para minimizar stat() calls sobre SMB.
Cada DirEntry ya trae stat cacheado del listado, evitando roundtrips.
"""
from __future__ import annotations

import fnmatch
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .config import Target


@dataclass(frozen=True)
class Candidate:
    path: Path
    size: int
    mtime: float
    target_name: str


def _matches_any(name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def scan_target(target: Target, now: float | None = None) -> Iterator[Candidate]:
    """Genera candidatos de un target. Ignora silenciosamente errores por
    archivo individual (permisos, race conditions) para que un fallo puntual
    no aborte la corrida entera; el logger los registra aparte."""
    now = now or time.time()
    cutoff = now - target.older_than_days * 86400

    yield from _walk(
        root=target.root,
        current=target.root,
        depth=0,
        max_depth=target.max_depth,
        patterns=target.patterns,
        cutoff=cutoff,
        target_name=target.name,
    )


def _walk(
    root: Path,
    current: Path,
    depth: int,
    max_depth: int,
    patterns: tuple[str, ...],
    cutoff: float,
    target_name: str,
) -> Iterator[Candidate]:
    try:
        it = os.scandir(current)
    except (FileNotFoundError, PermissionError, OSError):
        return

    with it:
        for entry in it:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if depth < max_depth:
                        yield from _walk(
                            root, Path(entry.path), depth + 1,
                            max_depth, patterns, cutoff, target_name,
                        )
                    continue

                if not entry.is_file(follow_symlinks=False):
                    continue
                if not _matches_any(entry.name, patterns):
                    continue

                st = entry.stat(follow_symlinks=False)
                if st.st_mtime > cutoff:
                    continue

                yield Candidate(
                    path=Path(entry.path),
                    size=st.st_size,
                    mtime=st.st_mtime,
                    target_name=target_name,
                )
            except (FileNotFoundError, PermissionError, OSError):
                continue
