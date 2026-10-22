"""FA-08 (#517): the Persian injection matrix judges code points, and only code points.

What this file proves without a desktop: that the fixture set covers every content
class the issue names and is drawn from the contract vectors where those exist; that
the comparator calls a result EXACT only on code-point equality and says where the
first difference is; that each corruption hint fires on exactly the transformation it
names and stays silent on an unrelated mismatch; that a result document which omits
the OS, backend or version, or whose verdicts disagree with its own code points, is
rejected; and that captures are paired with fixtures by time, so one silent fixture
cannot shift every later result.

What it cannot prove, and does not claim: that any backend on any real OS delivers
these strings. That is the matrix itself, run by a person on each platform
(docs/contribute/persian-injection-matrix.md).
"""
from __future__ import annotations

import ast
import importlib.util
import json
import shlex
import sys
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "scripts" / "injectmatrix"
SCRIPT = HERE / "injectmatrix.py"

_spec = importlib.util.spec_from_file_location("injectmatrix", SCRIPT)
assert _spec and _spec.loader
im = importlib.util.module_from_spec(_spec)
sys.modules["injectmatrix"] = im
_spec.loader.exec_module(im)

FIXTURES = im.load_fixtures()
BY_ID = {f.id: f for f in FIXTURES}


def _env(**over: object) -> dict:
    env = {
        "os": "linux", "os_version": "Ubuntu 24.04.1 LTS", "session": "x11",
        "yazses_version": "yazses 2.43.2", "backend": "xdotool", "backend_version": None,
        "receiver": "tk", "target_app": "injectmatrix Tk receiver (Tk 9.0.4)",
        "target_app_version": None, "python_version": "3.12.0",
    }
    env.update(over)
    return env


def _result(cases: list[dict] | None = None, **env_over: object) -> dict:
    if cases is None:
        cases = [im.build_case(f, f.text) for f in FIXTURES]
    return im.build_result(_env(**env_over), cases, fixture_set=im.fixture_set_id(),
                           recorded_at="2026-10-21T10:00:00+00:00")


# ------------------------------------------------------------------------ fixtures


def test_fixture_ids_are_unique_and_categories_known() -> None:
    ids = [f.id for f in FIXTURES]
    assert len(ids) == len(set(ids))
    for f in FIXTURES:
        assert f.categories, f.id
        assert set(f.categories) <= set(im.CATEGORIES), f.id
        assert f.text and f.why, f.id


def test_every_required_content_class_is_covered() -> None:
    covered = {c for f in FIXTURES for c in f.categories}
    assert set(im.REQUIRED_CATEGORIES) <= covered


def test_category_labels_match_the_text() -> None:
    """A label the text does not earn would make a matrix cell claim an untested class."""
    for f in FIXTURES:
        t = f.text
        if "zwnj" in f.categories:
            assert "\u200c" in t, f.id
        if "multiline" in f.categories:
            assert "\n" in t, f.id
        if "emoji" in f.categories:
            assert any(ord(c) > 0xFFFF for c in t), f.id
        if "digits" in f.categories:
            assert any(unicodedata.category(c) == "Nd" for c in t), f.id
        if "persian" in f.categories:
            assert any("\u0600" <= c <= "\u06ff" for c in t), f.id
        if "mixed" in f.categories:
            assert any("a" <= c.lower() <= "z" for c in t), f.id


@pytest.mark.parametrize(
    "fixture", [f for f in FIXTURES if f.source != "synthetic"], ids=lambda f: f.id
)
def test_sourced_fixtures_equal_their_contract_vector(fixture) -> None:
    """Drawn from contract/vectors, and still equal to it -- a vector edit cannot drift."""
    src = fixture.source
    assert src["file"].startswith("contract/vectors/")
    doc = json.loads((ROOT / src["file"]).read_text(encoding="utf-8"))
    value = next(c for c in doc["cases"] if c["id"] == src["case"])
    for part in src["field"].split("."):
        value = value[part]
    assert value == fixture.text


def test_no_fixture_is_dictated_text() -> None:
    """Acceptance: no private dictated text is needed. Every string is synthetic or a vector."""
    for f in FIXTURES:
        assert f.source == "synthetic" or f.source["file"].startswith("contract/vectors/"), f.id


def test_fixtures_file_writes_invisible_characters_as_escapes() -> None:
    """A raw ZWNJ in the JSON is invisible in review; an edit could drop it unseen."""
    raw = (HERE / "fixtures.json").read_text(encoding="utf-8")
    hidden = [f"U+{ord(c):04X}" for c in raw if unicodedata.category(c) in ("Cf", "Mn")]
    assert hidden == []


def test_fixture_set_id_names_the_texts() -> None:
    fs = im.fixture_set_id()
    assert fs["version"] == "1"
    assert len(fs["sha256"]) == 64


# ---------------------------------------------------------------------- comparator


def test_exact_means_code_point_equality() -> None:
    for f in FIXTURES:
        cmp = im.compare(f.text, f.text)
        assert (cmp.verdict, cmp.first_divergence, cmp.hints) == ("EXACT", None, ())


def test_visually_identical_text_is_not_exact() -> None:
    """Arabic yeh looks like Persian yeh. The comparator must not be fooled by a glyph."""
    cmp = im.compare("ی", "ي")
    assert cmp.verdict == "MISMATCH"
    assert cmp.first_divergence["index"] == 0
    assert cmp.first_divergence["expected"] == "U+06CC"
    assert cmp.first_divergence["received"] == "U+064A"


def test_nothing_received() -> None:
    cmp = im.compare("سلام", "")
    assert cmp.verdict == "NOTHING"
    assert cmp.first_divergence == {"index": 0, "expected": "U+0633", "received": None,
                                    "expected_name": "ARABIC LETTER SEEN",
                                    "received_name": None}


def test_first_divergence_on_truncation_and_extra_text() -> None:
    assert im.first_divergence("abcd", "ab")["index"] == 2
    assert im.first_divergence("abcd", "ab")["received"] is None
    assert im.first_divergence("ab", "abX")["expected"] is None
    assert im.first_divergence("ab", "abX")["received"] == "U+0058"


def test_receiver_limit_is_not_blamed_on_the_backend() -> None:
    assert im.compare("🚀", "\ud83d\ude80", receiver_ok=False).verdict == "RECEIVER_LIMIT"
    assert im.compare("🚀", "🚀", receiver_ok=False).verdict == "EXACT"


ZWNJ = BY_ID["fa-zwnj"].text
MULTI = BY_ID["fa-multiline"].text


@pytest.mark.parametrize(
    ("expected", "received", "hint"),
    [
        (ZWNJ, ZWNJ.replace("\u200c", ""), "zwnj-dropped"),
        (ZWNJ, ZWNJ.replace("\u200c", " "), "zwnj-as-space"),
        ("آب", unicodedata.normalize("NFD", "آب"), "normalized-NFD"),
        ("ک ی", "ك ي", "arabic-persian-letter-swap"),
        ("ك ي", "ک ی", "arabic-persian-letter-swap"),
        ("خط ۴۲ و ٤٢", "خط 42 و 42", "digits-to-ascii"),
        (MULTI, MULTI.replace("\n", "\r\n"), "newline-translated"),
        (MULTI, MULTI.replace("\n", " "), "newlines-dropped"),
        ("سلام دنیا", "سلام", "truncated"),
        ("سلام", "سلامسلام", "repeated"),
        ("سلام", "سلام دنیا", "extra-text"),
        ("سلام", "سلام\n", "trailing-newline-added"),
        ("ok 🚀", "ok \ud83d\ude80", "lone-surrogates"),
        ("ok سلام", "ok \ufffd\ufffd", "replacement-characters"),
        ("ok سلام", "ok ????", "non-ascii-as-question-marks"),
        ("\u202bسلام\u202c", "سلام", "bidi-controls-dropped"),
        ("سلام", "مالس", "same-code-points-reordered"),
    ],
)
def test_each_hint_fires_on_its_own_transformation(expected, received, hint) -> None:
    assert hint in im.corruption_hints(expected, received)
    assert im.compare(expected, received).verdict == "MISMATCH"


def test_an_uncatalogued_mismatch_gets_no_hint() -> None:
    """A hint that fires on anything teaches people to ignore hints (AGENTS.md rule 9)."""
    assert im.corruption_hints("سلام دنیا", "xyz") == ()
    assert im.corruption_hints("abc", "abd") == ()


def test_hints_never_fire_on_an_exact_match() -> None:
    for f in FIXTURES:
        assert im.corruption_hints(f.text, f.text) == ()


# ---------------------------------------------------------------- result document


def test_a_complete_result_validates() -> None:
    assert im.validate_result(_result(), FIXTURES) == []


@pytest.mark.parametrize("field", ["os_version", "yazses_version", "backend", "target_app"])
@pytest.mark.parametrize("value", ["", "unknown", None])
def test_result_must_identify_os_backend_and_version(field, value) -> None:
    problems = im.validate_result(_result(**{field: value}), FIXTURES)
    assert any(f"environment.{field}" in p for p in problems), problems


def test_missing_environment_field_is_reported() -> None:
    doc = _result()
    del doc["environment"]["backend_version"]
    assert "environment missing 'backend_version'" in im.validate_result(doc, FIXTURES)


def test_session_must_fit_the_os() -> None:
    assert im.validate_result(_result(session="none"), FIXTURES)
    assert im.validate_result(_result(os="windows", session="x11"), FIXTURES)
    assert im.validate_result(_result(os="windows", session="none"), FIXTURES) == []


def test_a_verdict_that_lies_about_its_code_points_is_rejected() -> None:
    case = im.build_case(BY_ID["fa-zwnj"], ZWNJ.replace("\u200c", ""))
    case["codepoint_verdict"] = "EXACT"
    problems = im.validate_result(_result([case]), FIXTURES)
    assert any("says EXACT but the code points give MISMATCH" in p for p in problems)


def _with_selftest(cases: list[dict], selftest: object) -> dict:
    doc = _result(cases)
    doc["receiver_selftest"] = selftest
    return doc


@pytest.mark.parametrize("selftest", [{"fa-zwnj": True}, {}, None])
def test_a_backend_failure_cannot_be_relabelled_receiver_limit(selftest) -> None:
    """RECEIVER_LIMIT excuses a mismatch only when the receiver's self-test says so.

    A dropped ZWNJ is a backend failure; calling it RECEIVER_LIMIT while the self-test
    shows the window held that text (or never ran) must not validate.
    """
    case = im.build_case(BY_ID["fa-zwnj"], ZWNJ.replace("\u200c", ""))
    case["codepoint_verdict"] = "RECEIVER_LIMIT"
    doc = _with_selftest([case], selftest)
    doc["summary"] = im.summarize([case])
    problems = im.validate_result(doc, FIXTURES)
    assert any("says RECEIVER_LIMIT but the code points give MISMATCH" in p
               for p in problems), problems


def test_a_receiver_limit_backed_by_the_selftest_validates() -> None:
    emoji = BY_ID["fa-emoji"]
    lossy = emoji.text.replace("\U0001f680", "\ud83d\ude80")
    assert lossy != emoji.text
    case = im.build_case(emoji, lossy, receiver_ok=False)
    assert case["codepoint_verdict"] == "RECEIVER_LIMIT"
    assert im.validate_result(_with_selftest([case], {"fa-emoji": False}), FIXTURES) == []


def test_receiver_limit_on_an_exact_case_is_rejected() -> None:
    """Even a failed self-test cannot excuse text that arrived exactly: that is EXACT."""
    emoji = BY_ID["fa-emoji"]
    case = im.build_case(emoji, emoji.text)
    case["codepoint_verdict"] = "RECEIVER_LIMIT"
    doc = _with_selftest([case], {"fa-emoji": False})
    doc["summary"] = im.summarize([case])
    problems = im.validate_result(doc, FIXTURES)
    assert any("says RECEIVER_LIMIT but the code points give EXACT" in p for p in problems)


@pytest.mark.parametrize("selftest", [["fa-emoji"], {"fa-emoji": "false"}, "no"])
def test_a_malformed_receiver_selftest_is_rejected(selftest) -> None:
    problems = im.validate_result(_with_selftest(None, selftest), FIXTURES)
    assert "receiver_selftest must be null or an object of booleans" in problems


def test_doctored_expectation_is_rejected() -> None:
    """Editing the expected side to match what arrived must not turn a failure into a pass."""
    received = ZWNJ.replace("\u200c", "")
    case = im.build_case(im.Fixture("fa-zwnj", ("zwnj",), received, "synthetic", ""), received)
    problems = im.validate_result(_result([case]), FIXTURES)
    assert any("differ from the shipped fixture" in p for p in problems)


def test_unknown_and_duplicate_cases_are_rejected() -> None:
    a = im.build_case(BY_ID["fa-plain"], BY_ID["fa-plain"].text)
    ghost = im.build_case(im.Fixture("not-a-fixture", ("persian",), "x", "synthetic", ""), "x")
    problems = im.validate_result(_result([a, a, ghost]), FIXTURES)
    assert any("appears twice" in p for p in problems)
    assert any("not in the shipped fixture set" in p for p in problems)


def test_summary_must_agree_with_cases() -> None:
    doc = _result()
    doc["summary"]["exact"] = 0
    assert any(p.startswith("summary.exact") for p in im.validate_result(doc, FIXTURES))


def test_corruption_and_layout_are_separate_fields() -> None:
    """Acceptance: Unicode corruption and visual-layout bugs are filed separately."""
    case = im.build_case(BY_ID["fa-plain"], BY_ID["fa-plain"].text)
    assert case["codepoint_verdict"] == "EXACT"
    assert case["visual_check"] == {"status": "pending", "notes": ""}


def _schema() -> dict:
    return json.loads((HERE / "result.schema.json").read_text(encoding="utf-8"))


def test_schema_file_and_validator_require_the_same_fields() -> None:
    s = _schema()
    props = s["properties"]
    assert s["required"] == list(im.REQUIRED_TOP_LEVEL)
    assert props["environment"]["required"] == list(im.REQUIRED_ENVIRONMENT)
    assert props["cases"]["items"]["required"] == list(im.REQUIRED_CASE)
    assert props["summary"]["required"] == list(im.REQUIRED_SUMMARY)
    assert props["schema_version"]["const"] == im.SCHEMA_VERSION
    assert props["kind"]["const"] == im.RESULT_KIND


def test_schema_file_and_validator_share_the_enums() -> None:
    props = _schema()["properties"]
    env = props["environment"]["properties"]
    case = props["cases"]["items"]["properties"]
    assert env["os"]["enum"] == list(im.OS_VALUES)
    assert env["session"]["enum"] == list(im.SESSION_VALUES)
    assert env["receiver"]["enum"] == list(im.RECEIVERS)
    assert case["codepoint_verdict"]["enum"] == list(im.CODEPOINT_VERDICTS)
    assert case["visual_check"]["properties"]["status"]["enum"] == list(im.VISUAL_STATUSES)
    assert case["categories"]["items"]["enum"] == list(im.CATEGORIES)


# ------------------------------------------------------------------ capture pairing


def _cap(t: float, text: str) -> dict:
    return {"type": "capture", "first_change": t, "code_points": im.code_points(text)}


def test_a_silent_fixture_does_not_shift_later_results() -> None:
    timeline = [{"fixture_id": "a", "start": 10.0}, {"fixture_id": "b", "start": 20.0},
                {"fixture_id": "c", "start": 30.0}]
    received, stray = im.assign_captures(timeline, [_cap(11.0, "A"), _cap(31.5, "C")])
    assert received == {"a": "A", "b": "", "c": "C"}
    assert stray == 0


def test_a_split_capture_is_joined_and_stray_input_is_counted() -> None:
    timeline = [{"fixture_id": "a", "start": 10.0}, {"fixture_id": "b", "start": 20.0}]
    caps = [_cap(25.0, "lo"), _cap(5.0, "typed before the run"), _cap(21.0, "hel")]
    received, stray = im.assign_captures(timeline, caps)
    assert received == {"a": "", "b": "hello"}
    assert stray == 1


class _FakeText:
    """The three Tk Text methods the round-trip uses; `lossy` mimics a UCS-2 Tcl."""

    def __init__(self, lossy: bool) -> None:
        self.buf, self.lossy = "", lossy

    def delete(self, *_a: object) -> None:
        self.buf = ""

    def insert(self, _index: str, text: str) -> None:
        self.buf += "".join("\ufffd" if self.lossy and ord(c) > 0xFFFF else c for c in text)

    def get(self, *_a: object) -> str:
        return self.buf


def test_receiver_roundtrip_catches_a_receiver_that_cannot_hold_emoji() -> None:
    emoji = BY_ID["fa-emoji"].text
    assert im.receiver_roundtrip(_FakeText(lossy=False), emoji) is True
    assert im.receiver_roundtrip(_FakeText(lossy=True), emoji) is False
    assert im.receiver_roundtrip(_FakeText(lossy=True), BY_ID["fa-zwnj"].text) is True


# ----------------------------------------------------------------------- rendering


def test_render_separates_corruption_from_layout() -> None:
    cases = [im.build_case(f, f.text) for f in FIXTURES]
    bad = next(c for c in cases if c["fixture_id"] == "fa-zwnj")
    bad.update(im.build_case(BY_ID["fa-zwnj"], ZWNJ.replace("\u200c", "")))
    layout = next(c for c in cases if c["fixture_id"] == "fa-punctuation-quotes")
    layout["visual_check"] = {"status": "fail", "notes": "parentheses not mirrored"}
    doc = _result(cases)
    doc["summary"] = im.summarize(cases)
    out = im.render_matrix([doc])
    table, rest = out.split("Code-point failures", 1)
    corruption, visual = rest.split("Visual-layout failures", 1)
    assert "FAIL: fa-zwnj" in table and "| fail |" in table
    assert "`fa-zwnj` MISMATCH" in corruption and "zwnj-dropped" in corruption
    assert "fa-punctuation-quotes" not in corruption
    assert "parentheses not mirrored" in visual and "fa-zwnj" not in visual


def test_render_does_not_blame_the_backend_for_a_receiver_limit() -> None:
    """A case the receiver could not hold is not a code-point failure to file."""
    emoji = BY_ID["fa-emoji"]
    assert "emoji" in emoji.categories
    cases = [im.build_case(f, f.text) for f in FIXTURES]
    limited = next(c for c in cases if c["fixture_id"] == "fa-emoji")
    limited.update(im.build_case(emoji, emoji.text.replace("\U0001f680", "\ud83d\ude80"),
                                 receiver_ok=False))
    assert limited["codepoint_verdict"] == "RECEIVER_LIMIT"
    doc = _result(cases)
    out = im.render_matrix([doc])
    table, rest = out.split("Code-point failures", 1)
    corruption, rest = rest.split("Visual-layout failures", 1)
    visual, limits = rest.split("Receiver limits", 1)
    assert "FAIL" not in table
    # persian and emoji both hold fa-emoji beside fixtures that arrived exactly
    assert table.count("EXACT (receiver limit, not tested: fa-emoji)") == 2
    assert "fa-emoji`" not in corruption and "- none" in corruption
    assert "fa-emoji" not in visual
    assert "`fa-emoji` RECEIVER_LIMIT" in limits
    # a column whose only case hit the limit says "not tested", never EXACT or FAIL
    alone = im.render_matrix([_result([limited])]).split("Code-point failures", 1)[0]
    assert alone.count("not tested (receiver limit: fa-emoji)") == 2
    assert "FAIL" not in alone


def test_render_says_not_tested_for_an_absent_class() -> None:
    doc = _result([im.build_case(BY_ID["en-control"], BY_ID["en-control"].text)])
    assert "not tested" in im.render_matrix([doc])


# --------------------------------------------------------------------- the commands


@pytest.fixture
def linux_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """The commands read the host; pin it so the suite means the same on every runner."""
    monkeypatch.setattr(im, "detect_environment", lambda: {
        "os": "linux", "os_version": "Detected Linux", "session": "x11",
        "python_version": "3.12.0"})


def test_compare_command_on_a_raw_file(tmp_path: Path, linux_host: None) -> None:
    received = tmp_path / "out.txt"
    received.write_bytes((BY_ID["fa-multiline"].text + "\n").encode("utf-8"))
    out = tmp_path / "r.json"
    argv = ["compare", "--fixture", "fa-multiline", "--received", str(received),
            "--out", str(out), "--backend", "xdotool", "--yazses-version", "2.43.2",
            "--target-app", "Firefox", "--session", "x11", "--os-version", "Test OS 1"]
    assert im.main(argv) == 0  # a valid result that records a MISMATCH
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["cases"][0]["codepoint_verdict"] == "MISMATCH"
    assert "trailing-newline-added" in doc["cases"][0]["corruption_hints"]

    assert im.main([*argv, "--strip-final-newline"]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["cases"][0]["codepoint_verdict"] == "EXACT"
    assert doc["receiver_normalization"] == "strip-one-final-newline"


def test_compare_keeps_invalid_utf8_visible(tmp_path: Path, linux_host: None) -> None:
    received = tmp_path / "out.txt"
    received.write_bytes("سلام".encode() + b"\xff")
    out = tmp_path / "r.json"
    assert im.main(["compare", "--fixture", "fa-plain", "--received", str(received), "--out", str(out),
             "--backend", "clipboard", "--yazses-version", "2.43.2", "--target-app", "gedit"]) == 0
    case = json.loads(out.read_text(encoding="utf-8"))["cases"][0]
    assert case["codepoint_verdict"] == "MISMATCH"
    assert "lone-surrogates" in case["corruption_hints"]


def test_visual_command_updates_the_summary(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text(json.dumps(_result()), encoding="utf-8")
    assert im.main(["visual", str(path), "--case", "fa-plain", "--status", "fail",
                    "--notes", "words in LTR order"]) == 0
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["summary"]["visual_fail"] == 1
    assert im.validate_result(doc, FIXTURES) == []


_FAKE_YAZSES = """\
import json, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("yazses 9.9.9")
    sys.exit(0)
assert args[0] == "inject"
text = args[-1]
print("Backend: fakebackend")
with open(sys.argv[0] + ".got", "a", encoding="utf-8") as fh:
    fh.write(json.dumps(text) + "\\n")
"""


def _command(*argv: str) -> str:
    if sys.platform == "win32":
        return " ".join(f'"{a}"' for a in argv)
    return shlex.join(argv)


def test_drive_passes_every_fixture_through_argv_unchanged(tmp_path: Path) -> None:
    """The driver must not be the thing that corrupts Persian, newlines or emoji."""
    fake = tmp_path / "fake_yazses.py"
    fake.write_text(_FAKE_YAZSES, encoding="utf-8")
    timeline = tmp_path / "t.jsonl"
    assert im.main(["drive", "--out", str(timeline), "--yazses", _command(sys.executable,
                    str(fake)), "--focus-delay", "0", "--gap", "0"]) == 0
    got = [json.loads(line) for line in
           (tmp_path / "fake_yazses.py.got").read_text(encoding="utf-8").splitlines()]
    assert got == [f.text for f in FIXTURES]
    rows = [json.loads(line) for line in timeline.read_text(encoding="utf-8").splitlines()]
    assert rows[0] == {"type": "meta", "yazses_version": "yazses 9.9.9"}
    assert {r["backend"] for r in rows[1:]} == {"fakebackend"}
    assert all(r["returncode"] == 0 for r in rows[1:])


def test_text_command_prints_the_fixture_byte_exact(capsysbinary: pytest.CaptureFixture) -> None:
    """The appprobe route feeds this to PROBE_TEXT; a stray newline would fail every run."""
    assert im.main(["text", "fa-boundary-zwnj"]) == 0
    assert capsysbinary.readouterr().out == BY_ID["fa-boundary-zwnj"].text.encode("utf-8")


def test_split_command_unquotes_a_windows_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(im, "os", SimpleNamespace(name="nt"))
    assert im.split_command(r'"C:\Program Files\YazSes\yazses-cli.exe" --x') == [
        r"C:\Program Files\YazSes\yazses-cli.exe", "--x"]


def test_assemble_writes_a_valid_result(tmp_path: Path, linux_host: None) -> None:
    ids = ["en-control", "fa-zwnj", "fa-emoji"]
    timeline = tmp_path / "t.jsonl"
    timeline.write_text("\n".join(json.dumps(r) for r in [
        {"type": "meta", "yazses_version": "yazses 2.43.2"},
        *({"type": "inject", "fixture_id": fid, "start": 100.0 + 10 * n, "end": 101.0 + 10 * n,
           "returncode": 0, "backend": "wtype"} for n, fid in enumerate(ids)),
    ]) + "\n", encoding="utf-8")
    captures = tmp_path / "c.jsonl"
    selftest = {f.id: f.id != "fa-emoji" for f in FIXTURES}
    captures.write_text("\n".join(json.dumps(r) for r in [
        {"type": "meta", "tk_patchlevel": "8.6.14", "receiver_selftest": selftest},
        _cap(100.5, BY_ID["en-control"].text),
        _cap(110.5, ZWNJ.replace("\u200c", "")),
        _cap(120.5, "خیلی عالی بود \ud83d\ude80"),
    ]) + "\n", encoding="utf-8")
    out = tmp_path / "r.json"
    assert im.main(["assemble", "--timeline", str(timeline), "--captures", str(captures),
             "--out", str(out), "--session", "wayland", "--os-version", "Fedora Linux 42"]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    verdicts = {c["fixture_id"]: c["codepoint_verdict"] for c in doc["cases"]}
    assert verdicts == {"en-control": "EXACT", "fa-zwnj": "MISMATCH",
                        "fa-emoji": "RECEIVER_LIMIT"}
    assert doc["environment"]["backend"] == "wtype"
    assert doc["environment"]["yazses_version"] == "yazses 2.43.2"
    assert "Tk 8.6.14" in doc["environment"]["target_app"]
    assert doc["environment"]["session"] == "wayland"
    assert im.validate_result(doc, FIXTURES) == []


# -------------------------------------------------------------------- the module


def test_harness_is_stdlib_only_and_has_no_network() -> None:
    """It must run on a bare Python on any OS, and it must not send anything anywhere."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    assert names <= set(sys.stdlib_module_names) | {"__future__"}, names
    assert not names & {"socket", "urllib", "http", "ssl", "ftplib", "smtplib"}
