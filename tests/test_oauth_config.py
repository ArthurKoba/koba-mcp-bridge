from koba_mcp_bridge import server


def test_chatgpt_oauth_redirect_is_fixed() -> None:
    assert server._CHATGPT_OAUTH_REDIRECT == "https://chatgpt.com/connector_platform_oauth_redirect"
