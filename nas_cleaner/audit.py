"""Logging estructurado JSONL para auditoria.

Cada corrida escribe un archivo por dia con lineas JSON. Barato de parsear
para reportes posteriores. Nada de logging.getLogger() global: pasamos
instancias explicitas."""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AuditLogger:
    log_dir: Path
    run_id: str
    _fh: Any = None

    @classmethod
    def open(cls, log_dir: Path) -> 'AuditLogger':
        log_dir.mkdir(parents=True, exist_ok=True)
        run_id = time.strftime('%Y%m%dT%H%M%S')
        path = log_dir / f'nas_cleaner_{time.strftime("%Y%m%d")}.jsonl'
        fh = path.open('a', encoding='utf-8', buffering=1)  # line-buffered
        inst = cls(log_dir=log_dir, run_id=run_id, _fh=fh)
        inst.event('run_start', pid=os.getpid())
        return inst

    def event(self, kind: str, **fields: Any) -> None:
        rec = {
            'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'run_id': self.run_id,
            'kind': kind,
            **fields,
        }
        self._fh.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')

    def close(self, summary: dict[str, Any]) -> None:
        self.event('run_end', **summary)
        self._fh.close()


def print_stderr(msg: str) -> None:
    print(msg, file=sys.stderr)
