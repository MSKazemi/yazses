"""CLI exposure for the acronym glossary (ADR-v2-114) — persistent store + expand."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from yazses import cli

runner = CliRunner()


@pytest.fixture()
def glossary(tmp_path, monkeypatch):
    path = tmp_path / "acronyms.json"
    monkeypatch.setattr(cli, "_acronyms_path", lambda: path)
    return path


def test_add_list_remove(glossary):
    r = runner.invoke(cli.app, ["acronyms", "add", "API", "Application", "Programming", "Interface"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(cli.app, ["acronyms", "list"])
    assert "API" in r.output and "Application Programming Interface" in r.output
    r = runner.invoke(cli.app, ["acronyms", "remove", "api"])
    assert r.exit_code == 0, r.output
    assert "empty" in runner.invoke(cli.app, ["acronyms", "list"]).output.lower()


def test_expand_uses_stored_glossary(glossary):
    runner.invoke(cli.app, ["acronyms", "add", "API", "Application", "Programming", "Interface"])
    r = runner.invoke(cli.app, ["acronyms", "expand", "The API and the API"])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "The Application Programming Interface (API) and the API"


def test_expand_reads_stdin(glossary):
    runner.invoke(cli.app, ["acronyms", "add", "CPU", "Central", "Processing", "Unit"])
    r = runner.invoke(cli.app, ["acronyms", "expand"], input="the CPU heats up\n")
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "the Central Processing Unit (CPU) heats up"
