"""Mock HTTP boundary evidence, not deployed login/session acceptance."""

import httpx
import pytest

from polycolab.operations import staging_auth_probe


@pytest.mark.parametrize("mode", ["local", "oidc"])
def test_probe_uses_only_selected_credential(mode: str) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(401 if len(requests) == 1 else 200)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert staging_auth_probe.probe(
            {
                "STAGING_BASE_URL": "https://staging.example.org",
                "STAGING_AUTH_MODE": mode,
                "STAGING_OPERATOR_SESSION": "synthetic-session",
                "STAGING_OPERATOR_TOKEN": "synthetic.token",
            },
            client,
        )
    assert "cookie" not in requests[0].headers
    assert "authorization" not in requests[0].headers
    if mode == "local":
        assert requests[1].headers["cookie"] == "polycolab_session=synthetic-session"
        assert "authorization" not in requests[1].headers
    else:
        assert requests[1].headers["authorization"] == "Bearer synthetic.token"
        assert "cookie" not in requests[1].headers


@pytest.mark.parametrize("status", [200, 302, 403, 500])
def test_unexpected_anonymous_status_fails_without_sending_secret(status: int) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, headers={"location": "https://different.example.org"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert not staging_auth_probe.probe(
            {"STAGING_BASE_URL": "https://staging.example.org", "STAGING_OPERATOR_SESSION": "test"},
            client,
        )
    assert len(requests) == 1


def test_authenticated_redirect_is_not_followed_and_anonymous_cookies_are_discarded() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(401, headers={"set-cookie": "unexpected=session; Path=/"})
        assert "cookie" not in request.headers
        return httpx.Response(302, headers={"location": "https://different.example.org"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert not staging_auth_probe.probe(
            {
                "STAGING_BASE_URL": "https://staging.example.org",
                "STAGING_AUTH_MODE": "oidc",
                "STAGING_OPERATOR_TOKEN": "test.token",
            },
            client,
        )
    assert len(requests) == 2


@pytest.mark.parametrize(
    "override",
    [
        {"STAGING_BASE_URL": "http://staging.example.org"},
        {"STAGING_BASE_URL": "https://user:secret@staging.example.org"},
        {"STAGING_BASE_URL": "https://staging.example.org/?secret=value"},
        {"STAGING_BASE_URL": "https://staging.example.org/path"},
        {"STAGING_AUTH_MODE": "disabled"},
        {"STAGING_OPERATOR_SESSION": "bad; another=cookie"},
        {"STAGING_OPERATOR_SESSION": ""},
        {"STAGING_AUTH_COOKIE_NAME": "bad\r\nheader"},
        {"STAGING_AUTH_MODE": "oidc", "STAGING_OPERATOR_TOKEN": "bad\r\nheader"},
    ],
)
def test_invalid_configuration_never_connects(override: dict[str, str]) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not connect")

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError):
            staging_auth_probe.probe(
                {
                    "STAGING_BASE_URL": "https://staging.example.org",
                    "STAGING_OPERATOR_SESSION": "test",
                    **override,
                },
                client,
            )


def test_cli_redacts_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failed(*args: object) -> bool:
        raise RuntimeError("private-response-and-credential")

    monkeypatch.setattr(staging_auth_probe, "probe", failed)
    assert staging_auth_probe.main() == 1
    assert capsys.readouterr().out == '{"status": "AUTH_BOUNDARY_FAILURE"}\n'
