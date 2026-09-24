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
            if imported.startswith("management."):
                violations.append(f"{path.relative_to(_SRC)} -> {imported}")
    assert violations == []


def test_bridge_does_not_import_provider_or_management_implementation() -> None:
    violations: list[str] = []
    for path in _python_files(_SRC / "bridge"):
        for imported in _imports(path):
            if imported == "modules" or imported.startswith("modules."):
                violations.append(f"{path.relative_to(_SRC)} -> {imported}")
            if imported.startswith("management."):
                violations.append(f"{path.relative_to(_SRC)} -> {imported}")
    assert violations == []


def test_provider_packages_do_not_import_each_other_or_management_implementation() -> None:
    violations: list[str] = []
    provider_roots = {
        "github": _SRC / "modules" / "github",
        "gitlab": _SRC / "modules" / "gitlab",
        "files": _SRC / "modules" / "files",
        "curl": _SRC / "modules" / "curl",
        "analysis": _SRC / "modules" / "analysis",
        "ghidra": _SRC / "modules" / "ghidra",
    }
    for provider, root in provider_roots.items():
        forbidden = {
            f"modules.{other}"
            for other in provider_roots
            if other not in {provider, "files"}
        }
        for path in _python_files(root):
            for imported in _imports(path):
                if imported.startswith("management."):
                    violations.append(f"{path.relative_to(_SRC)} -> {imported}")
                if any(
                    imported == prefix or imported.startswith(prefix + ".")
                    for prefix in forbidden
                ):
                    violations.append(f"{path.relative_to(_SRC)} -> {imported}")
    assert violations == []


def test_management_layers_depend_inward() -> None:
    violations: list[str] = []
    domain = _SRC / "management" / "domain"
    application = _SRC / "management" / "application"
    forbidden_domain = (
        "management.application",
        "management.infrastructure",
        "management.presentation",
        "fastapi",
        "sqlalchemy",
        "starlette_admin",
    )
    forbidden_application = (
        "management.infrastructure",
        "management.presentation",
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
    for root in (_SRC / "bridge", _SRC / "modules", _SRC / "management"):
        for path in _python_files(root):
            violations.extend(_environment_accesses(path))
    assert violations == []


def test_process_settings_are_created_only_in_composition_roots() -> None:
    violations: list[str] = []
    settings_types = {
        "AnalysisSettings",
        "BridgeSettings",
        "ManagementClientSettings",
        "ManagementSettings",
        "CurlSettings",
        "FileSettings",
        "GitHubPolicySettings",
        "GitLabSettings",
        "GhidraSettings",
        "PrivateRuntimeSettings",
    }
    allowed = {_SRC / "bridge" / "server.py", _SRC / "management" / "runtime.py"}
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


def test_provider_tool_catalog_is_not_conditionally_registered() -> None:
    violations: list[str] = []

    def visit(node: ast.AST, path: Path, conditional: bool = False) -> None:
        now_conditional = conditional or isinstance(
            node,
            (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match),
        )
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_tool = any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "tool"
                for decorator in node.decorator_list
            )
            if is_tool and conditional:
                violations.append(
                    f"{path.relative_to(_SRC)}:{node.lineno} {node.name} is conditional"
                )
        for child in ast.iter_child_nodes(node):
            visit(child, path, now_conditional)

    for provider in ("github", "gitlab"):
        root = _SRC / "modules" / provider
        for path in sorted(root.glob("*tools.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            visit(tree, path)

    assert violations == []


def test_github_actions_tools_use_one_account_selected_client_factory() -> None:
    path = _SRC / "modules" / "github" / "github_actions_tools.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    registrar = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "register_github_actions_tools"
    )
    parameters = [argument.arg for argument in registrar.args.args]
    assert "client_factory" in parameters
    assert "reviewer_client_factory" not in parameters
    assert "reviewer_available" not in parameters
