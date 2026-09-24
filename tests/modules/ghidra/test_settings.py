from common.settings import AnalysisSettings, BridgeSettings, GhidraSettings


def test_ghidra_service_is_the_internal_public_backend() -> None:
    assert BridgeSettings().ghidra_url == "http://ghidra:8000/mcp"
    assert AnalysisSettings().backend_url == "http://ghidra:8000/mcp"


def test_ghidra_service_targets_native_backend() -> None:
    assert GhidraSettings().backend_url == "http://bridge:8081/mcp"
