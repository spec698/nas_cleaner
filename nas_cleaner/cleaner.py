"""Motor de limpieza: aplica el borrado (o el move-to-trash) sobre los
candidatos, con circuit breaker y validacion de seguridad ultima instancia.
"""
from __future__ import annotations

import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from .audit import AuditLogger
from .config import Config, Target
from .safety import SafetyViolation, assert_safe_to_delete
from .scanner import Candidate, scan_target


@dataclass
class RunStats:
    scanned: int = 0
    would_delete: int = 0
    deleted: int = 0
    skipped_safety: int = 0
    errors: int = 0
    bytes_freed: int = 0


def _plan_target(target: Target) -> list[Candidate]:
    return list(scan_target(target))


def run(config: Config, apply: bool, audit: AuditLogger,
        only_targets: set[str] | None = None) -> RunStats:
    stats = RunStats()
    targets = [t for t in config.targets
               if only_targets is None or t.name in only_targets]

    audit.event('plan_start', targets=[t.name for t in targets], apply=apply)

    # Fase 1: enumerar candidatos en paralelo por raiz.
    candidates_by_target: dict[str, list[Candidate]] = {}
    with ThreadPoolExecutor(max_workers=config.workers) as ex:
        futures = {ex.submit(_plan_target, t): t for t in targets}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                cands = fut.result()
            except Exception as e:
                audit.event('scan_error', target=t.name, error=str(e))
                stats.errors += 1
                cands = []
            candidates_by_target[t.name] = cands
            stats.scanned += len(cands)
            audit.event('scan_done', target=t.name, candidates=len(cands))

    stats.would_delete = stats.scanned

    # Circuit breaker: si excede el limite, aborta antes de borrar nada.
    if stats.would_delete > config.max_deletes_per_run:
        audit.event('circuit_breaker_tripped',
                    would_delete=stats.would_delete,
                    limit=config.max_deletes_per_run)
        return stats

    if not apply:
        # Dry-run: registrar cada candidato y salir.
        for tname, cands in candidates_by_target.items():
            for c in cands:
                audit.event('would_delete',
                            target=tname, path=str(c.path),
                            size=c.size, mtime=c.mtime)
        return stats

    # Fase 2: borrar. Un target a la vez para evitar contencion en la misma
    # carpeta; dentro del target, secuencial (SMB no premia paralelismo aqui).
    forbidden = config.forbidden_roots
    for t in targets:
        for c in candidates_by_target.get(t.name, []):
            try:
                resolved = assert_safe_to_delete(c.path, t.root, forbidden)
            except SafetyViolation as sv:
                audit.event('safety_skip', path=str(c.path), reason=str(sv))
                stats.skipped_safety += 1
                continue

            try:
                if config.trash_dir is not None:
                    _move_to_trash(resolved, t.root, config.trash_dir)
                    action = 'trashed'
                else:
                    resolved.unlink()
                    action = 'deleted'
                stats.deleted += 1
                stats.bytes_freed += c.size
                audit.event(action, target=t.name, path=str(resolved),
                            size=c.size, mtime=c.mtime)
            except (OSError, PermissionError) as e:
                stats.errors += 1
                audit.event('delete_error', path=str(resolved), error=str(e))

    return stats


def _move_to_trash(src: Path, target_root: Path, trash_dir: Path) -> None:
    """Mueve `src` bajo trash_dir preservando ruta relativa al target_root,
    con prefijo de fecha para permitir purga por antiguedad."""
    day = time.strftime('%Y%m%d')
    try:
        rel = src.resolve().relative_to(target_root.resolve())
    except ValueError:
        rel = Path(src.name)
    dest = trash_dir / day / target_root.name / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
