from __future__ import annotations

from types import SimpleNamespace

from modules.analysis.result import decode_call_result, decode_result


def test_decode_result_parses_raw_json_string() -> None:
    result = decode_result('{"has_project":true,"project_name":"camera"}')
    assert result["has_project"] is True
    assert result["project_name"] == "camera"


def test_decode_result_recursively_unwraps_result_envelopes() -> None:
    result = decode_result({"result": '{"result":{"value":7}}'})
    assert result == {"value": 7}


def test_decode_call_result_prefers_structured_content() -> None:
    result = SimpleNamespace(
        data={"value": "lossy"},
        structured_content={"result": '{"value":"exact"}'},
        content=[],
    )
    assert decode_call_result(result) == {"value": "exact"}


def test_decode_call_result_falls_back_to_text_content() -> None:
    result = SimpleNamespace(
        data=None,
        structured_content=None,
        content=[SimpleNamespace(text='{"value":"text"}')],
    )
    assert decode_call_result(result) == {"value": "text"}
