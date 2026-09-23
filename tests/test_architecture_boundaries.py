from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def test_common_layer_is_provider_neutral() -> None:
    violations: list[str] = []
    for path in _python_files(_SRC / "common"):
        for imported in _imports(path):
            if imported == "modules" or imported.startswith("modules."):
                violations.append(f"{path.relative_to(_SRC)} -> {imported}")
            if imported == "bridge" or imported.startswith("bridge."):
                violations.append(f"{path.relative_to(_SRC)} -> {imported}")
    assert violations == []


def test_bridge_does_not_import_provider_implementations() -> None:
    violations: list[str] = []
    for path in _python_files(_SRC / "bridge"):
        for imported in _imports(path):
            if imported == "modules" or imported.startswith("modules."):
                violations.append(f"{path.relative_to(_SRC)} -> {imported}")
    assert violations == []


def test_provider_packages_do_not_import_each_other() -> None:
    violations: list[str] = []
    provider_roots = {
        "github": _SRC / "modules" / "github",
        "gitlab": _SRC / "modules" / "gitlab",
        "files": _SRC / "modules" / "files",
        "curl": _SRC / "modules" / "curl",
        "analysis": _SRC / "modules" / "analysis",
    }
    for provider, root in provider_roots.items():
        forbidden = {
            f"modules.{other}"
            for other in provider_roots
            if other not in {provider, "files"}
        }
        for path in _python_files(root):
            for imported in _imports(path):
                if any(
                    imported == prefix or imported.startswith(prefix + ".")
                    for prefix in forbidden
                ):
                    violations.append(f"{path.relative_to(_SRC)} -> {imported}")
    assert violations == []
