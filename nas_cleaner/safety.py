"""Validaciones de seguridad sobre paths.

Regla de oro: antes de tocar cualquier archivo, resolver symlinks y
verificar que el path final sigue *dentro* de la raiz declarada del target
y NO cae bajo ninguna forbidden_root. Esto bloquea escapes por symlink.
"""
from __future__ import annotations

from pathlib import Path


def _resolve(p: Path) -> Path:
    # strict=False: permite paths inexistentes (aunque en el flow real
    # siempre existen porque venimos de scandir).
    return p.resolve(strict=False)


def is_within(child: Path, parent: Path) -> bool:
    """True si `child` esta bajo `parent` tras resolver symlinks."""
    child_r = _resolve(child)
    parent_r = _resolve(parent)
    try:
        child_r.relative_to(parent_r)
    except ValueError:
        return False
    return True


class SafetyViolation(Exception):
    pass


def assert_safe_to_delete(
    file_path: Path,
    target_root: Path,
    forbidden_roots: tuple[Path, ...],
) -> Path:
    """Devuelve el path resuelto si es seguro; lanza SafetyViolation si no.

    Chequeos:
    1. El path resuelto debe seguir dentro del target_root declarado.
    2. El path resuelto no debe caer bajo ninguna forbidden_root.
    3. El path debe ser un archivo regular (no directorio, no symlink a dir).
    """
    resolved = _resolve(file_path)

    if not is_within(resolved, target_root):
        raise SafetyViolation(
            f'escape de target_root: {file_path} -> {resolved} '
            f'(esperado bajo {target_root})'
        )

    for forbidden in forbidden_roots:
        if is_within(resolved, forbidden):
            raise SafetyViolation(
                f'ruta prohibida: {resolved} cae bajo {forbidden}'
            )

    # No borramos directorios, y evitamos symlinks apuntando fuera.
    if file_path.is_symlink():
        raise SafetyViolation(f'no se borran symlinks: {file_path}')
    if not resolved.is_file():
        raise SafetyViolation(f'no es archivo regular: {resolved}')

    return resolved
