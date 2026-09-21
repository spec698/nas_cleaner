"""CLI. Dry-run por defecto; requiere --apply explicito para borrar."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config as config_mod
from .audit import AuditLogger, print_stderr
from .cleaner import run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='nas_cleaner',
        description='Limpieza allowlist-first sobre rutas de NAS.',
    )
    p.add_argument('--config', '-c', required=True, type=Path,
                   help='Ruta al YAML de configuracion.')
    p.add_argument('--apply', action='store_true',
                   help='Ejecutar borrado real. Sin este flag: dry-run.')
    p.add_argument('--target', '-t', action='append', default=None,
                   help='Filtra a targets con este nombre (repetible).')
    p.add_argument('--log-dir', type=Path, default=Path('./logs'),
                   help='Carpeta para JSONL de auditoria.')
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        cfg = config_mod.load(args.config)
    except (config_mod.ConfigError, FileNotFoundError) as e:
        print_stderr(f'error de config: {e}')
        return 2

    only = set(args.target) if args.target else None
    audit = AuditLogger.open(args.log_dir)

    try:
        stats = run(cfg, apply=args.apply, audit=audit, only_targets=only)
    finally:
        audit.close(summary=dict(
            scanned=getattr(stats, 'scanned', 0),
            would_delete=getattr(stats, 'would_delete', 0),
            deleted=getattr(stats, 'deleted', 0),
            skipped_safety=getattr(stats, 'skipped_safety', 0),
            errors=getattr(stats, 'errors', 0),
            bytes_freed=getattr(stats, 'bytes_freed', 0),
            apply=args.apply,
        ))

    mode = 'APPLY' if args.apply else 'DRY-RUN'
    print(f'[{mode}] candidatos={stats.would_delete} '
          f'borrados={stats.deleted} skip_seguridad={stats.skipped_safety} '
          f'errores={stats.errors} bytes={stats.bytes_freed}')

    if stats.would_delete > cfg.max_deletes_per_run:
        print_stderr('CIRCUIT BREAKER: se abortó antes de borrar. '
                     'Revisar config o subir max_deletes_per_run.')
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())
