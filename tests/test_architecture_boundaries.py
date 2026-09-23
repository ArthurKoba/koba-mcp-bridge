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
            if imported.startswith("control_plane."):
                violations.append(f"{path.relative_to(_SRC)} -> {imported}")
    assert violations == []


def test_bridge_does_not_import_provider_or_control_plane_implementation() -> None:
    violations: list[str] = []
    for path in _python_files(_SRC / "bridge"):
        for imported in _imports(path):
            if imported == "modules" or imported.startswith("modules."):
                violations.append(f"{path.relative_to(_SRC)} -> {imported}")
            if imported.startswith("control_plane."):
                violations.append(f"{path.relative_to(_SRC)} -> {imported}")
    assert violations == []


def test_provider_packages_do_not_import_each_other_or_control_plane_implementation() -> None:
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
                if imported.startswith("control_plane."):
                    violations.append(f"{path.relative_to(_SRC)} -> {imported}")
                if any(
                    imported == prefix or imported.startswith(prefix + ".")
                    for prefix in forbidden
                ):
                    violations.append(f"{path.relative_to(_SRC)} -> {imported}")
    assert violations == []


def test_control_plane_layers_depend_inward() -> None:
    violations: list[str] = []
    domain = _SRC / "control_plane" / "domain"
    application = _SRC / "control_plane" / "application"
    forbidden_domain = (
        "control_plane.application",
        "control_plane.infrastructure",
        "control_plane.presentation",
        "fastapi",
        "sqlalchemy",
        "starlette_admin",
    )
    forbidden_application = (
        "control_plane.infrastructure",
        "control_plane.presentation",
        "fastapi",
        "sqlalchemy",
        "starlette_admin",
    )
    for root, forbidden in ((domain, forbidden_domain), (application, forbidden_application)):
        for path in _python_files(root):
            violations.extend(
                f"{path.relative_to(_SRC)} -> {imported}"
                for imported in _imports(path)
                if any(
                    imported == item or imported.startswith(item + ".")
                    for item in forbidden
                )
            )
    assert violations == []


def _environment_accesses(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    accesses: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if not isinstance(node.value, ast.Name) or node.value.id != "os":
            continue
        if node.attr in {"getenv", "environ", "environb", "putenv", "unsetenv"}:
            accesses.append(f"{path.relative_to(_SRC)}:{node.lineno} os.{node.attr}")
    return accesses


def test_process_environment_is_not_read_inside_application_or_provider_code() -> None:
    violations: list[str] = []
    for root in (_SRC / "bridge", _SRC / "modules", _SRC / "control_plane"):
        for path in _python_files(root):
            violations.extend(_environment_accesses(path))
    assert violations == []


def test_process_settings_are_created_only_in_composition_roots() -> None:
    violations: list[str] = []
    settings_types = {
        "AnalysisSettings",
        "BridgeSettings",
        "ControlPlaneClientSettings",
        "ControlPlaneSettings",
        "CurlSettings",
        "FileSettings",
        "GitHubPolicySettings",
        "GitLabSettings",
        "PrivateRuntimeSettings",
    }
    allowed = {_SRC / "bridge" / "server.py", _SRC / "control_plane" / "runtime.py"}
    allowed.update((_SRC / "modules").glob("*/runtime.py"))

    for path in _python_files(_SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id not in settings_types:
                continue
            if path not in allowed:
                violations.append(
                    f"{path.relative_to(_SRC)}:{node.lineno} constructs {node.func.id}"
                )
    assert violations == []


def test_infisical_is_not_part_of_runtime_source() -> None:
    violations: list[str] = []
    for path in _python_files(_SRC):
        text = path.read_text(encoding="utf-8").casefold()
        if "infisical" in text:
            violations.append(str(path.relative_to(_SRC)))
    assert violations == []


def _tool_functions(path: Path) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "tool"
            for decorator in node.decorator_list
        ):
            result.append(node)
    return result


def test_provider_tools_use_explicit_account_id() -> None:
    violations: list[str] = []
    exceptions = {"github_accounts", "accounts"}
    for provider in ("github", "gitlab"):
        root = _SRC / "modules" / provider
        for path in sorted(root.glob("*tools.py")):
            for function in _tool_functions(path):
                if function.name in exceptions:
                    continue
                args = function.args.args
                first = args[0].arg if args else ""
                if first != "account_id":
                    violations.append(
                        f"{path.relative_to(_SRC)}:{function.lineno} "
                        f"{function.name} first={first!r}"
                    )
    assert violations == []
