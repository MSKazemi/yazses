"""Tests for the offline LLM dictation cleanup (Python path).

Mirrors the Rust engine's guarantees: disabled/missing-backend/empty/guard-fail
all return the input unchanged; only a guard-passing reformat is accepted.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from yazses.config import DisfluencyConfig
from yazses.postprocess.llm_cleanup import (
    LlmCleaner,
    _critical_tokens,
    _length_ratio_ok,
    _tokens_preserved,
    build_cleaner,
    endpoint_is_permitted,
    is_loopback_endpoint,
)

# ── guards ──────────────────────────────────────────────────────────────────

def test_length_ratio_rejects_too_short_and_too_long():
    inp = "abcdefghijklmnopqrst"  # 20
    assert _length_ratio_ok(inp, "abcdefghijklmno", 0.5, 2.0)  # 15 ok
    assert not _length_ratio_ok(inp, "abcde", 0.5, 2.0)  # 5 too short
    assert not _length_ratio_ok(inp, "x" * 50, 0.5, 2.0)  # 50 too long


def test_length_ratio_empty_input_passes():
    assert _length_ratio_ok("", "", 0.5, 2.0)
    assert _length_ratio_ok("", "hello", 0.5, 2.0)


def test_critical_tokens_picks_numbers_ids_urls_proper_nouns():
    toks = _critical_tokens("deploy snake_case_fn to https://x.io at 0900 for Acme")
    assert "snake_case_fn" in toks
    assert "https://x.io" in toks
    assert "0900" in toks
    assert "Acme" in toks  # proper noun (uppercase) via _is_protected
    assert "deploy" not in toks


def test_tokens_preserved_detects_drops():
    assert _tokens_preserved("deploy at 0900", "Deploy at 0900.")
    assert not _tokens_preserved("deploy at 0900", "Deploy.")
    assert not _tokens_preserved("call snake_case_fn now", "Call it now.")


# ── cleaner behaviour ─────────────────────────────────────────────────────────

def _enabled_config() -> DisfluencyConfig:
    return DisfluencyConfig(llm_enabled=True, llm_model="", llm_endpoint="")


def test_build_cleaner_none_when_disabled():
    assert build_cleaner(DisfluencyConfig(llm_enabled=False)) is None


def test_build_cleaner_instance_when_enabled():
    assert isinstance(build_cleaner(DisfluencyConfig(llm_enabled=True)), LlmCleaner)


def test_disabled_returns_input():
    cleaner = LlmCleaner(DisfluencyConfig(llm_enabled=False))
    assert cleaner.cleanup("hello world") == "hello world"


def test_empty_input_returns_input():
    cleaner = LlmCleaner(_enabled_config())
    assert cleaner.cleanup("   ") == "   "


def test_no_backend_returns_input():
    # llm_model empty AND llm_endpoint empty → _complete returns None.
    cleaner = LlmCleaner(_enabled_config())
    assert cleaner.cleanup("some real dictated text") == "some real dictated text"


def test_happy_path_accepts_reformat(mocker):
    cleaner = LlmCleaner(_enabled_config())
    mocker.patch.object(cleaner, "_complete", return_value="Hello, world.")
    assert cleaner.cleanup("hello world") == "Hello, world."


def test_guard_rejects_dropped_token(mocker):
    cleaner = LlmCleaner(_enabled_config())
    # LLM drops the number "0900" → token guard rejects → input returned.
    mocker.patch.object(cleaner, "_complete", return_value="Deploy to prod.")
    assert cleaner.cleanup("deploy to prod at 0900") == "deploy to prod at 0900"


def test_guard_rejects_runaway_length(mocker):
    cleaner = LlmCleaner(_enabled_config())
    mocker.patch.object(cleaner, "_complete", return_value="x " * 100)
    assert cleaner.cleanup("short input here") == "short input here"


def test_empty_model_output_returns_input(mocker):
    cleaner = LlmCleaner(_enabled_config())
    mocker.patch.object(cleaner, "_complete", return_value="   ")
    assert cleaner.cleanup("some real dictated text") == "some real dictated text"


def test_backend_exception_returns_input(mocker):
    cleaner = LlmCleaner(_enabled_config())
    mocker.patch.object(cleaner, "_complete", side_effect=RuntimeError("boom"))
    assert cleaner.cleanup("some real dictated text") == "some real dictated text"


def test_missing_local_model_file_disables_local_backend(mocker):
    cfg = DisfluencyConfig(llm_enabled=True, llm_model="/nonexistent/model.gguf", llm_endpoint="")
    cleaner = LlmCleaner(cfg)
    # No file → local backend yields None → cleanup returns input.
    assert cleaner.cleanup("some real dictated text") == "some real dictated text"


def test_ollama_backend_used_when_no_local_model(mocker):
    cfg = DisfluencyConfig(llm_enabled=True, llm_model="", llm_endpoint="http://localhost:11434")
    cleaner = LlmCleaner(cfg)
    spy = mocker.patch.object(cleaner, "_complete_ollama", return_value="Clean text at 0900.")
    out = cleaner.cleanup("clean text at 0900")
    assert out == "Clean text at 0900."
    spy.assert_called_once()


# ── endpoint locality: the "nothing leaves the machine" guard ────────────────

def test_loopback_endpoints_are_recognised():
    for url in (
        "http://localhost:11434",
        "http://LOCALHOST:11434",
        "http://localhost.localdomain:11434",
        "http://127.0.0.1:11434",
        "http://127.0.0.1",
        "https://127.5.6.7:443",       # all of 127.0.0.0/8 is loopback
        "http://[::1]:11434",
    ):
        assert is_loopback_endpoint(url), url


def test_remote_endpoints_are_rejected():
    for url in (
        "https://api.openai.com/v1",
        "http://192.168.1.50:11434",   # LAN is still off this machine
        "http://10.0.0.5:11434",
        "http://ollama.example.com:11434",
        "http://localhost.evil.com:11434",   # suffix trick, not localhost
        "http://[2001:db8::1]:11434",
        # Userinfo bypass: urlsplit puts the credential outside `hostname`, so
        # the real target here is evil.com. Classic, and easy to get wrong.
        "http://127.0.0.1@evil.com:11434",
        "http://localhost@evil.com",
        # Not addresses at all. Refusing means one logged sentence instead of a
        # urllib ValueError traceback on every dictation burst.
        "not a url",
        "",
        "localhost:11434",   # no scheme -> urlsplit finds no host
    ):
        assert not is_loopback_endpoint(url), url


def test_a_name_that_resolves_to_loopback_is_still_not_trusted():
    """DNS is not a security boundary.

    `localtest.me` and friends resolve to 127.0.0.1 today and to whatever the
    zone owner likes tomorrow, and the answer can change between the check and
    the connect. Classifying by resolution would make the guard depend on the
    network it exists to avoid.
    """
    assert not is_loopback_endpoint("http://localtest.me:11434")


def test_remote_endpoint_blocks_the_ollama_call(mocker):
    """The regression this guard exists for: transcribed text off-machine.

    Before the guard, `_complete` dispatched to `_complete_ollama` for any
    non-empty endpoint, so this configuration POSTed dictated text to a remote
    host. This test fails without the guard.
    """
    cfg = DisfluencyConfig(
        llm_enabled=True, llm_model="", llm_endpoint="https://api.example.com"
    )
    cleaner = LlmCleaner(cfg)
    spy = mocker.patch.object(cleaner, "_complete_ollama", return_value="Sent!")
    assert cleaner.cleanup("my private dictation") == "my private dictation"
    spy.assert_not_called()


def test_explicit_opt_out_permits_a_remote_endpoint(mocker):
    cfg = DisfluencyConfig(
        llm_enabled=True,
        llm_model="",
        llm_endpoint="https://api.example.com",
        llm_allow_remote_endpoint=True,
    )
    cleaner = LlmCleaner(cfg)
    spy = mocker.patch.object(cleaner, "_complete_ollama", return_value="Clean text at 0900.")
    assert cleaner.cleanup("clean text at 0900") == "Clean text at 0900."
    spy.assert_called_once()


def test_remote_endpoint_warns_once_not_per_burst(caplog):
    cfg = DisfluencyConfig(
        llm_enabled=True, llm_model="", llm_endpoint="https://api.example.com"
    )
    cleaner = LlmCleaner(cfg)
    with caplog.at_level("WARNING"):
        for _ in range(5):
            cleaner.cleanup("some real dictated text")
    warnings = [r for r in caplog.records if "not a loopback address" in r.getMessage()]
    assert len(warnings) == 1


def test_local_gguf_model_is_unaffected_by_a_remote_endpoint(mocker):
    """A configured local model never reaches the endpoint branch at all."""
    cfg = DisfluencyConfig(
        llm_enabled=True, llm_model="/some/model.gguf", llm_endpoint="https://api.example.com"
    )
    cleaner = LlmCleaner(cfg)
    spy = mocker.patch.object(cleaner, "_complete_local", return_value="Clean text at 0900.")
    assert cleaner.cleanup("clean text at 0900") == "Clean text at 0900."
    spy.assert_called_once()


def test_default_config_is_loopback():
    """Ollama's own default must stay permitted, or the feature breaks for everyone."""
    assert is_loopback_endpoint(DisfluencyConfig().llm_endpoint)
    assert endpoint_is_permitted(DisfluencyConfig())
    assert DisfluencyConfig().llm_allow_remote_endpoint is False


# ── doctor surfacing ────────────────────────────────────────────────────────

def _cfg_with(**kw):
    from yazses.config import FiltersConfig, load_config

    cfg = load_config(None)
    cfg.filters = FiltersConfig(disfluency=DisfluencyConfig(**kw))
    return cfg


def test_doctor_is_silent_when_cleanup_is_off():
    from yazses.system.doctor import _llm_endpoint_check

    assert _llm_endpoint_check(_cfg_with(llm_enabled=False)) == []


def test_doctor_reports_loopback_as_ok():
    from yazses.system.doctor import _llm_endpoint_check

    (name, status, detail), = _llm_endpoint_check(
        _cfg_with(llm_enabled=True, llm_endpoint="http://localhost:11434")
    )
    assert (name, status) == ("LLM cleanup", "OK")
    assert "loopback" in detail


def test_doctor_warns_that_a_remote_endpoint_is_disabled():
    from yazses.system.doctor import _llm_endpoint_check

    (_, status, detail), = _llm_endpoint_check(
        _cfg_with(llm_enabled=True, llm_endpoint="https://api.example.com")
    )
    assert status == "WARN"
    assert "disabled" in detail


def test_doctor_warns_loudly_when_remote_is_actually_permitted():
    from yazses.system.doctor import _llm_endpoint_check

    (_, status, detail), = _llm_endpoint_check(
        _cfg_with(
            llm_enabled=True,
            llm_endpoint="https://api.example.com",
            llm_allow_remote_endpoint=True,
        )
    )
    assert status == "WARN"
    assert "off this machine" in detail


def test_doctor_says_a_local_model_makes_no_network_call():
    from yazses.system.doctor import _llm_endpoint_check

    (_, status, detail), = _llm_endpoint_check(
        _cfg_with(llm_enabled=True, llm_model="/some/model.gguf")
    )
    assert status == "OK"
    assert "no network call" in detail


# ── the HTTP backend, against a real in-process loopback server ─────────────
#
# No mocks of urllib: a `ThreadingHTTPServer` bound to 127.0.0.1 on an ephemeral port
# records what the cleaner actually sent and answers with a canned body. Nothing leaves
# the machine, and the request the test inspects is the request the code built.

class _FakeServer:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.reply: dict = {}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server's naming
                length = int(self.headers.get("Content-Length", "0"))
                outer.requests.append((self.path, json.loads(self.rfile.read(length))))
                body = json.dumps(outer.reply).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                pass

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.endpoint = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def fake_server():
    server = _FakeServer()
    yield server
    server.close()


def _http_config(endpoint: str, **kw) -> DisfluencyConfig:
    return DisfluencyConfig(
        llm_enabled=True, llm_model="", llm_endpoint=endpoint, llm_timeout_ms=5000, **kw
    )


def test_ollama_default_model_is_unchanged_for_existing_installs(fake_server):
    fake_server.reply = {"response": "Deploy at 0900."}
    cleaner = LlmCleaner(_http_config(fake_server.endpoint))
    assert cleaner.cleanup("deploy at 0900") == "Deploy at 0900."
    (path, payload), = fake_server.requests
    assert path == "/api/generate"
    assert payload["model"] == "qwen2.5:1.5b"


def test_ollama_sends_the_configured_model(fake_server):
    """The bug: the model was hardcoded, so any other model 404'd into raw text."""
    fake_server.reply = {"response": "Deploy at 0900."}
    cleaner = LlmCleaner(_http_config(fake_server.endpoint, llm_endpoint_model="llama3.2:3b"))
    assert cleaner.cleanup("deploy at 0900") == "Deploy at 0900."
    (_, payload), = fake_server.requests
    assert payload["model"] == "llama3.2:3b"


def test_endpoint_model_defaults_to_empty():
    assert DisfluencyConfig().llm_endpoint_model == ""


def test_ollama_asks_for_no_thinking(fake_server):
    fake_server.reply = {"response": "Deploy at 0900."}
    LlmCleaner(_http_config(fake_server.endpoint)).cleanup("deploy at 0900")
    (_, payload), = fake_server.requests
    assert payload["think"] is False


# ── llm_api = "openai": the chat-completions shape ─────────────────────────

def _chat_reply(content) -> dict:
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]}


def test_api_defaults_to_ollama():
    assert DisfluencyConfig().llm_api == "ollama"


def test_openai_path_url_payload_and_model(fake_server):
    fake_server.reply = _chat_reply("Deploy at 0900.")
    cfg = _http_config(
        fake_server.endpoint + "/",  # a trailing slash must not double up
        llm_api="openai",
        llm_endpoint_model="qwen3.5-2b",
        llm_max_tokens=128,
    )
    assert LlmCleaner(cfg).cleanup("deploy at 0900") == "Deploy at 0900."
    (path, payload), = fake_server.requests
    assert path == "/v1/chat/completions"
    assert payload == {
        "model": "qwen3.5-2b",
        "messages": [
            {"role": "system", "content": cfg.llm_system_prompt},
            {"role": "user", "content": "deploy at 0900"},
        ],
        "temperature": 0,
        "max_tokens": 128,
        "stream": False,
    }


def test_openai_path_sends_a_custom_prompt_as_the_system_message(fake_server):
    fake_server.reply = _chat_reply("Deploy at 0900.")
    cleaner = LlmCleaner(_http_config(fake_server.endpoint, llm_api="openai"))
    cleaner.cleanup("deploy at 0900", custom_prompt="Be terse.")
    (_, payload), = fake_server.requests
    assert payload["messages"][0] == {"role": "system", "content": "Be terse."}


def test_openai_api_value_is_matched_case_insensitively(fake_server):
    """configcheck accepts `"OpenAI"` (it compares lowered), so the consumer must too."""
    fake_server.reply = _chat_reply("Deploy at 0900.")
    LlmCleaner(_http_config(fake_server.endpoint, llm_api=" OpenAI ")).cleanup("deploy at 0900")
    (path, _), = fake_server.requests
    assert path == "/v1/chat/completions"


def test_openai_path_strips_a_leading_think_block(fake_server):
    fake_server.reply = _chat_reply(
        "<think>\nThe user wants punctuation. 0900 must stay.\n</think>\n\nDeploy at 0900."
    )
    cleaner = LlmCleaner(_http_config(fake_server.endpoint, llm_api="openai"))
    assert cleaner.cleanup("deploy at 0900") == "Deploy at 0900."


def test_a_reply_that_is_only_thinking_is_rejected(fake_server):
    fake_server.reply = _chat_reply("<think>deploy at 0900, so the answer is</think>   ")
    cleaner = LlmCleaner(_http_config(fake_server.endpoint, llm_api="openai"))
    assert cleaner.cleanup("deploy at 0900") == "deploy at 0900"


def test_an_unclosed_think_block_is_rejected(fake_server):
    """The token budget ran out mid-thought: there is no answer to type."""
    fake_server.reply = _chat_reply("<think>deploy at 0900. Let me consider")
    cleaner = LlmCleaner(_http_config(fake_server.endpoint, llm_api="openai"))
    assert cleaner.cleanup("deploy at 0900") == "deploy at 0900"


def test_openai_reply_that_drops_a_number_is_rejected(fake_server):
    fake_server.reply = _chat_reply("Transfer the dollars.")
    cleaner = LlmCleaner(_http_config(fake_server.endpoint, llm_api="openai"))
    assert cleaner.cleanup("transfer 100 dollars") == "transfer 100 dollars"


def test_openai_reply_that_changes_a_number_is_rejected(fake_server):
    fake_server.reply = _chat_reply("Transfer 1000 dollars.")
    cleaner = LlmCleaner(_http_config(fake_server.endpoint, llm_api="openai"))
    assert cleaner.cleanup("transfer 100 dollars") == "transfer 100 dollars"


@pytest.mark.parametrize(
    "reply",
    [{}, {"choices": []}, {"choices": [{"message": {"content": None}}]}, ["not", "a", "dict"]],
)
def test_openai_malformed_reply_returns_input(fake_server, reply):
    fake_server.reply = reply
    cleaner = LlmCleaner(_http_config(fake_server.endpoint, llm_api="openai"))
    assert cleaner.cleanup("deploy at 0900") == "deploy at 0900"


def test_openai_server_down_returns_input():
    # Bind and close a socket so the port is known to be free, then point at it.
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    cleaner = LlmCleaner(_http_config(f"http://127.0.0.1:{port}", llm_api="openai"))
    assert cleaner.cleanup("deploy at 0900") == "deploy at 0900"


def test_remote_endpoint_is_refused_on_the_openai_path_too(mocker):
    """The API style must not open a second door past the loopback guard."""
    cfg = DisfluencyConfig(
        llm_enabled=True, llm_model="", llm_endpoint="https://api.openai.com", llm_api="openai"
    )
    cleaner = LlmCleaner(cfg)
    post = mocker.patch.object(cleaner, "_post_json")
    openai = mocker.spy(cleaner, "_complete_openai")
    assert cleaner.cleanup("my private dictation") == "my private dictation"
    post.assert_not_called()
    openai.assert_not_called()


def test_the_openai_path_goes_through_the_same_socket_as_ollama():
    """One primitive, one gate: both shapes use `_post_json`, which `_complete` guards."""
    import inspect

    from yazses.postprocess import llm_cleanup

    src = inspect.getsource(llm_cleanup)
    assert src.count("urlopen(") == 1
    assert "_post_json(" in inspect.getsource(LlmCleaner._complete_openai)
    assert "_post_json(" in inspect.getsource(LlmCleaner._complete_ollama)


def test_strip_think_leaves_an_ordinary_answer_alone():
    from yazses.postprocess.llm_cleanup import _strip_think

    assert _strip_think("Deploy at 0900.") == "Deploy at 0900."
    # Only a *leading* block is reasoning; a later mention is content.
    assert _strip_think("Use the <think> tag.</think>") == "Use the <think> tag.</think>"


def test_config_rejects_an_unknown_api_and_keeps_the_default(tmp_path):
    from yazses.config import load_config_checked

    path = tmp_path / "config.toml"
    path.write_text('[filters.disfluency]\nllm_api = "opneai"\n', encoding="utf-8")
    result = load_config_checked(path)
    assert result.config.filters.disfluency.llm_api == "ollama"
    (problem,) = [p for p in result.problems if p.key == "llm_api"]
    assert "openai" in str(problem)


@pytest.mark.parametrize("value", ["ollama", "openai"])
def test_config_accepts_both_documented_apis(tmp_path, value):
    from yazses.config import load_config_checked

    path = tmp_path / "config.toml"
    path.write_text(f'[filters.disfluency]\nllm_api = "{value}"\n', encoding="utf-8")
    result = load_config_checked(path)
    assert result.config.filters.disfluency.llm_api == value
    assert not result.problems
