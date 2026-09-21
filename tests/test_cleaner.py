"""Tests de humo del flujo completo, con un sandbox local que simula el NAS.

Cubren:
- allowlist: solo se borra lo que matchea un target
- forbidden_roots: bloquea aunque el path caiga bajo un target
- dry-run: no toca disco
- circuit breaker: aborta si excede max_deletes_per_run
- filtro por edad (older_than_days)
- filtro por patron
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from nas_cleaner.audit import AuditLogger
from nas_cleaner.cleaner import run
from nas_cleaner.config import Config, Target


def _touch(p: Path, age_days: float = 0.0, content: str = 'x') -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')
    if age_days:
        ts = time.time() - age_days * 86400
        os.utime(p, (ts, ts))
    return p


@pytest.fixture
def nas(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def audit(tmp_path: Path) -> AuditLogger:
    return AuditLogger.open(tmp_path / 'audit')


def _cfg(targets: list[Target], forbidden=(), max_deletes=10000,
         trash: Path | None = None) -> Config:
    return Config(
        targets=tuple(targets),
        forbidden_roots=tuple(forbidden),
        max_deletes_per_run=max_deletes,
        trash_dir=trash,
        trash_retention_days=7,
        workers=2,
    )


def test_dry_run_no_borra(nas, audit):
    reports = nas / 'reports'
    old = _touch(reports / 'a.csv', age_days=60)
    t = Target('rep', reports, ('*.csv',), older_than_days=30, max_depth=3)
    stats = run(_cfg([t]), apply=False, audit=audit)
    assert stats.would_delete == 1
    assert stats.deleted == 0
    assert old.exists()


def test_borra_solo_lo_que_matchea(nas, audit):
    reports = nas / 'reports'
    borrar = _touch(reports / 'r1.csv', age_days=60)
    conservar_ext = _touch(reports / 'r1.docx', age_days=60)
    conservar_edad = _touch(reports / 'r2.csv', age_days=1)
    t = Target('rep', reports, ('*.csv',), older_than_days=30, max_depth=3)
    stats = run(_cfg([t]), apply=True, audit=audit)
    assert stats.deleted == 1
    assert not borrar.exists()
    assert conservar_ext.exists()
    assert conservar_edad.exists()


def test_forbidden_root_bloquea_aunque_matchee(nas, audit):
    reports = nas / 'reports'
    # Un target apunta a reports, pero forbidden_roots lo prohibe entero.
    victima = _touch(reports / 'x.csv', age_days=60)
    t = Target('rep', reports, ('*.csv',), older_than_days=30, max_depth=3)
    stats = run(_cfg([t], forbidden=(reports,)), apply=True, audit=audit)
    assert stats.deleted == 0
    assert stats.skipped_safety == 1
    assert victima.exists()


def test_circuit_breaker_aborta(nas, audit):
    reports = nas / 'reports'
    for i in range(5):
        _touch(reports / f'f{i}.csv', age_days=60)
    t = Target('rep', reports, ('*.csv',), older_than_days=30, max_depth=3)
    stats = run(_cfg([t], max_deletes=3), apply=True, audit=audit)
    assert stats.deleted == 0  # aborta antes de tocar nada
    assert stats.would_delete == 5
    assert len(list(reports.iterdir())) == 5


def test_symlink_escape_es_rechazado(nas, audit):
    reports = nas / 'reports'
    reports.mkdir()
    prod = nas / 'prod'
    prod_file = _touch(prod / 'prod.csv', age_days=60)
    link = reports / 'link.csv'
    try:
        link.symlink_to(prod_file)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks no disponibles en este entorno')

    t = Target('rep', reports, ('*.csv',), older_than_days=30, max_depth=3)
    stats = run(_cfg([t]), apply=True, audit=audit)
    # El link ni siquiera aparece como archivo regular (is_file follow=False
    # sobre un symlink es False), o si aparece, safety lo rechaza.
    assert prod_file.exists()


def test_trash_dir_mueve_en_vez_de_borrar(nas, audit):
    reports = nas / 'reports'
    trash = nas / 'trash'
    victima = _touch(reports / 'r.csv', age_days=60)
    t = Target('rep', reports, ('*.csv',), older_than_days=30, max_depth=3)
    stats = run(_cfg([t], trash=trash), apply=True, audit=audit)
    assert stats.deleted == 1
    assert not victima.exists()
    # esta en algun lado bajo trash/
    moved = list(trash.rglob('r.csv'))
    assert len(moved) == 1
