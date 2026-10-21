"""One-click Windows update (ADR-027): plan, download, verify, hand off — all offline.

Nothing here touches the network or runs PowerShell. The release JSON, the checksum
file, the download and the detached launcher are all fakes; what is under test is the
decision logic and the job description handed to Windows. Whether Windows then runs
that job correctly can only be verified on Windows — see ADR-027's checklist.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
import yazses.system.installer_update as iu
from yazses.platform.base import Platform, UpdateHandoff, UpdateLauncher
from yazses.platform.windows import update_handoff as wh
from yazses.system.updater import RELEASES_URL, UpdateStatus, manual_update_steps

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "https://github.com/MSKazemi/yazses/releases/download/"
BLOB = b"MZ" + b"\x00fake inno installer\x00" * 500
SHA = hashlib.sha256(BLOB).hexdigest()


def _asset(name, *, tag="v2.44.0", size=None, url=None, digest=None):
    out = {
        "name": name,
        "browser_download_url": url or f"{PREFIX}{tag}/{name}",
        "size": len(BLOB) if size is None else size,
    }
    if digest is not None:
        out["digest"] = digest
    return out


def _payload(*assets, tag="v2.44.0", draft=False, prerelease=False):
    if not assets:
        assets = (
            _asset("YazSes-2.44.0-windows-x64.exe"),
            _asset("SHA256SUMS.txt", size=200),
            _asset("YazSes-2.44.0-macos-arm64.dmg"),
        )
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease, "assets": list(assets)}


def _sums(name="YazSes-2.44.0-windows-x64.exe", sha=SHA):
    return f"{'0' * 64}  yazses_2.44.0_amd64.deb\n{sha}  {name}\n"


def _status(method="windows-installer", **kw):
    base = dict(
        method=method, current="2.43.2", latest="2.44.0", available=True,
        command=None, note="", steps=manual_update_steps(method),
    )
    base.update(kw)
    return UpdateStatus(**base)


class _Resp:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(data: bytes, seen: list | None = None):
    def _open(url, timeout):
        if seen is not None:
            seen.append((url, timeout))
        return _Resp(data)

    return _open


class FakeLauncher:
    def __init__(self, tmp: Path, *, arch="x64", relaunch=None, fail=False, scope="user",
                 feed=None):
        self.tmp = tmp
        self.arch = arch
        self.relaunch = ["C:\\Users\\a\\AppData\\Local\\Programs\\YazSes\\YazSesApp.exe", "--tray"] \
            if relaunch is None else relaunch
        self.fail = fail
        self.scope = scope
        # What each package manager's own feed says; default: already at 2.44.0.
        self.feed = feed if feed is not None else {
            "choco": "yazses|2.44.0\n",
            "winget": "Found YazSes [MSKazemi.YazSes]\nVersion: 2.44.0\n",
            "scoop": "Name        : yazses\nVersion     : 2.44.0\n",
        }
        self.handoffs: list[UpdateHandoff] = []

    def install_scope(self):
        return self.scope

    def query_package_manager(self, method):
        return self.feed.get(method)

    def staging_dir(self):
        return self.tmp / "stage"

    def native_arch(self):
        return self.arch

    def relaunch_command(self):
        return self.relaunch

    def hand_off(self, handoff):
        if self.fail:
            raise OSError("powershell missing")
        self.handoffs.append(handoff)


# ---- asset selection --------------------------------------------------------

def test_x64_machine_gets_the_x64_installer():
    a = iu.select_installer_asset(_payload(), "x64")
    assert a.name == "YazSes-2.44.0-windows-x64.exe"
    assert a.version == "2.44.0" and a.arch == "x64" and a.size == len(BLOB)


def test_arm64_prefers_native_and_falls_back_to_x64():
    both = _payload(_asset("YazSes-2.44.0-windows-x64.exe"),
                    _asset("YazSes-2.44.0-windows-arm64.exe"))
    assert iu.select_installer_asset(both, "ARM64").arch == "arm64"
    assert iu.select_installer_asset(_payload(), "aarch64").arch == "x64"


def test_x64_never_takes_an_arm64_installer():
    only_arm = _payload(_asset("YazSes-2.44.0-windows-arm64.exe"))
    with pytest.raises(iu.UpdateRefused):
        iu.select_installer_asset(only_arm, "AMD64")


def test_unknown_arch_is_refused():
    with pytest.raises(iu.UpdateRefused):
        iu.select_installer_asset(_payload(), "x86")


def test_an_asset_for_another_version_is_ignored():
    stale = _payload(_asset("YazSes-2.43.2-windows-x64.exe"))
    with pytest.raises(iu.UpdateRefused, match="no Windows installer"):
        iu.select_installer_asset(stale, "x64")


@pytest.mark.parametrize("draft,pre", [(True, False), (False, True)])
def test_drafts_and_prereleases_are_refused(draft, pre):
    with pytest.raises(iu.UpdateRefused):
        iu.select_installer_asset(_payload(draft=draft, prerelease=pre), "x64")


def test_an_installer_served_from_elsewhere_is_refused():
    evil = _payload(_asset("YazSes-2.44.0-windows-x64.exe",
                           url="https://evil.example/YazSes-2.44.0-windows-x64.exe"))
    with pytest.raises(iu.UpdateRefused, match="not served from"):
        iu.select_installer_asset(evil, "x64")


def test_a_url_naming_a_different_file_is_refused():
    swapped = _payload(_asset("YazSes-2.44.0-windows-x64.exe",
                              url=f"{PREFIX}v2.44.0/other.exe"))
    with pytest.raises(iu.UpdateRefused):
        iu.select_installer_asset(swapped, "x64")


# ---- URL allowlists ---------------------------------------------------------

@pytest.mark.parametrize("url", [
    f"{PREFIX}v2.44.0/YazSes-2.44.0-windows-x64.exe",
    f"{PREFIX}v2.44.0/SHA256SUMS.txt",
])
def test_trusted_download_urls(url):
    assert iu.is_trusted_download_url(url)


@pytest.mark.parametrize("url", [
    "http://github.com/MSKazemi/yazses/releases/download/v1/x.exe",
    "https://github.com.evil.example/MSKazemi/yazses/releases/download/v1/x.exe",
    "https://evil@github.com/MSKazemi/yazses/releases/download/v1/x.exe",
    "https://github.com:8443/MSKazemi/yazses/releases/download/v1/x.exe",
    "https://github.com/MSKazemi/yazses-fork/releases/download/v1/x.exe",
    "https://github.com/someone/yazses/releases/download/v1/x.exe",
    "https://github.com/MSKazemi/yazses/releases/download/v1/../x.exe",
    "https://github.com/MSKazemi/yazses/releases/download/v1/a/x.exe",
    "https://github.com/MSKazemi/yazses/releases/download/v1/x.exe?x=1",
    "https://github.com/MSKazemi/yazses/releases/download/v1%2fx.exe",
    "https://github.com/MSKazemi/yazses/releases/download/x.exe",
    "",
    None,
    42,
])
def test_untrusted_download_urls(url):
    assert not iu.is_trusted_download_url(url)


@pytest.mark.parametrize("url,ok", [
    ("https://objects.githubusercontent.com/github-production-release-asset/1", True),
    ("https://release-assets.githubusercontent.com/x", True),
    ("https://github.com/MSKazemi/yazses/releases/download/v1/x.exe", True),
    ("http://objects.githubusercontent.com/x", False),
    ("https://githubusercontent.com.evil.example/x", False),
    ("https://evil.example/x", False),
    ("https://user@objects.githubusercontent.com/x", False),
    ("https://.githubusercontent.com/x", False),
])
def test_redirect_allowlist(url, ok):
    assert iu.is_allowed_redirect(url) is ok


def test_the_redirect_handler_refuses_a_foreign_host():
    import urllib.error

    handler = iu._GithubOnlyRedirects()
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example/x.exe")


# ---- checksums ------------------------------------------------------------

def test_parse_sha256sums_handles_both_sha256sum_modes():
    parsed = iu.parse_sha256sums(f"{SHA}  a.exe\n{'A' * 64} *b.dmg\nnot a line\n")
    assert parsed == {"a.exe": [SHA], "b.dmg": ["a" * 64]}


def test_expected_sha256_finds_the_asset():
    assert iu.expected_sha256(_sums(), "YazSes-2.44.0-windows-x64.exe") == SHA


def test_a_missing_entry_is_refused():
    with pytest.raises(iu.UpdateRefused, match="does not list"):
        iu.expected_sha256(_sums(name="other.exe"), "YazSes-2.44.0-windows-x64.exe")


def test_conflicting_entries_are_refused():
    text = _sums() + f"{'b' * 64}  YazSes-2.44.0-windows-x64.exe\n"
    with pytest.raises(iu.UpdateRefused, match="conflicting"):
        iu.expected_sha256(text, "YazSes-2.44.0-windows-x64.exe")


def test_github_digest_must_agree_when_present():
    name = "YazSes-2.44.0-windows-x64.exe"
    assert iu.expected_sha256(_sums(), name, api_digest=f"sha256:{SHA.upper()}") == SHA
    with pytest.raises(iu.UpdateRefused, match="disagree"):
        iu.expected_sha256(_sums(), name, api_digest="sha256:" + "c" * 64)


def test_checksums_url_must_be_trusted_and_present():
    assert iu.checksums_url(_payload()).endswith("/v2.44.0/SHA256SUMS.txt")
    with pytest.raises(iu.UpdateRefused, match="no SHA256SUMS"):
        iu.checksums_url(_payload(_asset("YazSes-2.44.0-windows-x64.exe")))
    with pytest.raises(iu.UpdateRefused):
        iu.checksums_url(_payload(_asset("SHA256SUMS.txt", url="https://evil.example/s")))


# ---- version gating -----------------------------------------------------------

@pytest.mark.parametrize("current", ["2.44.0", "2.45.0", "3.0.0"])
def test_only_a_strictly_newer_release_is_planned(current):
    with pytest.raises(iu.UpdateRefused, match="not newer"):
        iu.plan_installer(_payload(), current, "x64")


def test_a_newer_release_is_planned():
    assert iu.plan_installer(_payload(), "2.43.2", "x64").version == "2.44.0"


def test_an_oversized_asset_is_refused_before_download():
    big = _payload(_asset("YazSes-2.44.0-windows-x64.exe", size=iu.MAX_INSTALLER_BYTES + 1))
    with pytest.raises(iu.UpdateRefused, match="cap"):
        iu.plan_installer(big, "2.43.2", "x64")


# ---- installer and package-manager argv ---------------------------------------

def test_installer_arguments_are_a_silent_in_place_upgrade(tmp_path):
    args = iu.installer_arguments(tmp_path / "installer.log")
    for switch in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
                   "/CLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS"):
        assert switch in args
    # The job already waited for YazSes and aborts if it is still running; a force-close
    # could only destroy what that wait protects (a meeting still being saved).
    assert "/FORCECLOSEAPPLICATIONS" not in args
    assert args[-1] == f"/LOG={tmp_path / 'installer.log'}"
    # Never an uninstall, never a different directory.
    assert not any(a.upper().startswith(("/DIR=", "/UNINSTALL")) for a in args)


def test_package_manager_argv():
    choco, elevate, capture = iu.package_manager_argv("choco")
    assert choco[:2] == ["choco", "upgrade"] and elevate and not capture
    winget, elevate, capture = iu.package_manager_argv("winget")
    assert winget[:2] == ["winget", "upgrade"] and "--accept-source-agreements" in winget
    assert "--disable-interactivity" in winget and not elevate and capture
    scoop, elevate, capture = iu.package_manager_argv("scoop")
    assert scoop == ["scoop", "update", "yazses"] and not elevate and capture
    for method in ("windows-installer", "pip", "snap", "macos-app"):
        with pytest.raises(iu.UpdateRefused):
            iu.package_manager_argv(method)


def test_confirmation_prompt_is_honest_about_signing_and_uac():
    _title, text = iu.confirmation_prompt(_status())
    assert "SHA-256" in text and "not code-signed" in text and "start again" in text
    _title, text = iu.confirmation_prompt(_status("choco", command=["choco", "upgrade", "yazses", "-y"]))
    assert "choco upgrade yazses -y" in text and "administrator" in text


# ---- download + verify ----------------------------------------------------------

def _plan():
    return iu.plan_installer(_payload(), "2.43.2", "x64")


def test_download_verifies_and_renames(tmp_path):
    seen, events = [], []
    path = iu.download_verified(_plan(), SHA, tmp_path, open_url=_opener(BLOB, seen),
                                progress=lambda m, f: events.append((m, f)))
    assert path == tmp_path / "YazSes-2.44.0-windows-x64.exe"
    assert path.read_bytes() == BLOB
    assert not (tmp_path / (path.name + ".part")).exists()
    assert seen[0][0].startswith(PREFIX) and seen[0][1] == iu.READ_TIMEOUT_S
    assert ("Checking the SHA-256…", None) in events


def test_a_checksum_mismatch_deletes_and_refuses(tmp_path):
    with pytest.raises(iu.UpdateRefused, match="does not match"):
        iu.download_verified(_plan(), "d" * 64, tmp_path, open_url=_opener(BLOB))
    assert list(tmp_path.iterdir()) == []


def test_more_bytes_than_declared_is_refused(tmp_path):
    with pytest.raises(iu.UpdateRefused, match="larger"):
        iu.download_verified(_plan(), SHA, tmp_path, open_url=_opener(BLOB + b"x" * 70000))
    assert list(tmp_path.iterdir()) == []


def test_the_hard_cap_applies_without_a_declared_size(tmp_path):
    asset = iu.InstallerAsset(name="YazSes-2.44.0-windows-x64.exe", url=_plan().url,
                              size=None, version="2.44.0", arch="x64")
    with pytest.raises(iu.UpdateRefused, match="larger"):
        iu.download_verified(asset, SHA, tmp_path, open_url=_opener(BLOB), max_bytes=100)


def test_a_short_download_is_refused(tmp_path):
    with pytest.raises(iu.UpdateRefused, match="early"):
        iu.download_verified(_plan(), SHA, tmp_path, open_url=_opener(BLOB[:-10]))
    assert list(tmp_path.iterdir()) == []


def test_the_deadline_stops_a_slow_download(tmp_path):
    ticks = iter(range(0, 10_000, 1000))
    with pytest.raises(iu.UpdateRefused, match="too long"):
        iu.download_verified(_plan(), SHA, tmp_path, open_url=_opener(BLOB),
                             clock=lambda: float(next(ticks)), deadline_s=1500)
    assert list(tmp_path.iterdir()) == []


def test_a_network_error_is_a_refusal_not_a_traceback(tmp_path):
    def _boom(url, timeout):
        raise OSError("connection reset")

    with pytest.raises(iu.UpdateRefused, match="download failed"):
        iu.download_verified(_plan(), SHA, tmp_path, open_url=_boom)


def test_an_untrusted_asset_url_is_never_opened(tmp_path):
    asset = iu.InstallerAsset(name="x.exe", url="https://evil.example/x.exe", size=1,
                              version="2.44.0", arch="x64")
    opened = []
    with pytest.raises(iu.UpdateRefused):
        iu.download_verified(asset, SHA, tmp_path, open_url=_opener(BLOB, opened))
    assert opened == []


def test_fetch_release_payload_and_checksums_use_the_injected_opener():
    payload = iu.fetch_release_payload(open_url=_opener(json.dumps(_payload()).encode()))
    assert payload["tag_name"] == "v2.44.0"
    with pytest.raises(iu.UpdateRefused):
        iu.fetch_release_payload(open_url=_opener(b"not json"))
    assert SHA in iu.fetch_checksums(f"{PREFIX}v2.44.0/SHA256SUMS.txt",
                                     open_url=_opener(_sums().encode()))
    with pytest.raises(iu.UpdateRefused):
        iu.fetch_checksums("https://evil.example/SHA256SUMS.txt", open_url=_opener(b""))


# ---- the orchestration ----------------------------------------------------------

def _run(launcher, status=None, **kw):
    kw.setdefault("fetch_payload", lambda: _payload())
    kw.setdefault("fetch_sums", lambda url: _sums())
    kw.setdefault(
        "download",
        lambda asset, sha, dest, progress=None: iu.download_verified(
            asset, sha, dest, open_url=_opener(BLOB), progress=progress),
    )
    return iu.start_one_click_update(status or _status(), launcher, wait_pids=[11, 22, 0], **kw)


def test_the_installer_path_hands_off_a_verified_silent_upgrade(tmp_path):
    launcher = FakeLauncher(tmp_path)
    result = _run(launcher, now=lambda: 1000.0)
    assert result.ok, result.message
    (h,) = launcher.handoffs
    stage = tmp_path / "stage"
    assert h.kind == "installer" and not h.elevate and h.sha256 == SHA
    assert h.argv[0] == str(stage / "YazSes-2.44.0-windows-x64.exe")
    assert "/VERYSILENT" in h.argv
    assert h.wait_pids == (11, 22)
    assert h.relaunch == tuple(launcher.relaunch)
    assert h.cleanup == (stage / "YazSes-2.44.0-windows-x64.exe", stage / iu.LOCK_NAME)
    assert (stage / iu.LOCK_NAME).exists()  # held until the detached job deletes it
    pending = json.loads((stage / iu.PENDING_NAME).read_text(encoding="utf-8"))
    assert pending["from"] == "2.43.2" and pending["to"] == "2.44.0"
    assert pending["started"] == 1000.0


def test_a_package_manager_hands_off_its_own_command(tmp_path):
    launcher = FakeLauncher(tmp_path)
    called = []
    result = _run(launcher, _status("winget", command=["winget", "upgrade"]),
                  fetch_payload=lambda: called.append("net") or _payload())
    assert result.ok
    (h,) = launcher.handoffs
    assert h.kind == "package-manager" and h.argv[0] == "winget" and h.capture_output
    assert h.sha256 == "" and called == []  # nothing downloaded by us


@pytest.mark.parametrize("break_it", ["payload", "sums", "mismatch", "relaunch", "arch"])
def test_every_failure_falls_back_without_handing_off(tmp_path, break_it):
    launcher = FakeLauncher(tmp_path)
    kw = {}
    if break_it == "payload":
        def _no_network():
            raise iu.UpdateRefused("could not read the release from github.com")
        kw["fetch_payload"] = _no_network
    elif break_it == "sums":
        kw["fetch_sums"] = lambda url: _sums(name="other.exe")
    elif break_it == "mismatch":
        kw["fetch_sums"] = lambda url: _sums(sha="e" * 64)
    elif break_it == "relaunch":
        launcher.relaunch = []
    elif break_it == "arch":
        launcher.arch = "x86"
    result = _run(launcher, **kw)
    assert not result.ok
    assert launcher.handoffs == []
    assert "Nothing was installed" in result.message
    assert any(RELEASES_URL in s for s in result.steps)
    stage = tmp_path / "stage"
    leftovers = [p.name for p in stage.iterdir()] if stage.exists() else []
    assert not any(n.endswith((".exe", ".part")) for n in leftovers)
    assert iu.PENDING_NAME not in leftovers
    assert iu.LOCK_NAME not in leftovers  # a failed attempt must not block the next


def test_a_launcher_that_cannot_start_cleans_up(tmp_path):
    launcher = FakeLauncher(tmp_path, fail=True)
    result = _run(launcher)
    assert not result.ok and "could not start" in result.message
    assert [p.name for p in (tmp_path / "stage").iterdir()] == []


def test_unsupported_methods_and_no_launcher_fall_back(tmp_path):
    for status, launcher in (
        (_status("pip", command=["pip"]), FakeLauncher(tmp_path)),
        (_status(), None),
        (_status(available=False), FakeLauncher(tmp_path)),
    ):
        result = iu.start_one_click_update(status, launcher)
        assert not result.ok and result.steps


def test_one_click_supported():
    launcher = FakeLauncher(Path("."))
    assert iu.one_click_supported(_status(), launcher)
    assert iu.one_click_supported(_status("scoop"), launcher)
    assert not iu.one_click_supported(_status("uv"), launcher)
    assert not iu.one_click_supported(_status(), None)
    assert not iu.one_click_supported(_status(available=False), launcher)


# ---- reporting the result on the next start -------------------------------------

def test_success_is_judged_by_the_running_version():
    pending = {"from": "2.43.2", "to": "2.44.0", "log": "C:\\t\\update.log"}
    assert iu.describe_handoff_result(pending, "0", "2.44.0")[0] == "YazSes updated"
    # Exit 0 is not evidence: the version did not move.
    title, body = iu.describe_handoff_result(pending, "0", "2.43.2")
    assert title == "Update did not install" and "did not change the version" in body
    assert RELEASES_URL in body and "update.log" in body


@pytest.mark.parametrize("code,needle", [
    ("-1", "administrator"), ("-2", "SHA-256"), ("5", "cancelled"),
    ("4", "code 4"), (None, "did not report"),
])
def test_failure_reasons(code, needle):
    _t, body = iu.describe_handoff_result({"from": "1.0", "to": "1.1"}, code, "1.0")
    assert needle in body


def test_read_handoff_result_reports_once(tmp_path):
    (tmp_path / iu.PENDING_NAME).write_text(json.dumps({"from": "1.0", "to": "1.1"}),
                                            encoding="utf-8")
    (tmp_path / iu.RESULT_NAME).write_text("\ufeff0\r\n", encoding="utf-8")
    assert iu.read_handoff_result(tmp_path, "1.1")[0] == "YazSes updated"
    assert iu.read_handoff_result(tmp_path, "1.1") is None


def test_a_job_still_running_is_not_called_failed(tmp_path):
    (tmp_path / iu.PENDING_NAME).write_text(
        json.dumps({"from": "1.0", "to": "1.1", "started": 100}), encoding="utf-8")
    assert iu.read_handoff_result(tmp_path, "1.0", now=lambda: 200.0) is None
    assert (tmp_path / iu.PENDING_NAME).exists()
    late = iu.read_handoff_result(tmp_path, "1.0", now=lambda: 100 + 3600.0)
    assert late is not None and "did not report" in late[1]


def test_no_pending_record_reports_nothing(tmp_path):
    assert iu.read_handoff_result(tmp_path, "1.0") is None
    (tmp_path / iu.PENDING_NAME).write_text("{corrupt", encoding="utf-8")
    assert iu.read_handoff_result(tmp_path, "1.0") is None


# ---- the Windows launcher (pure parts) --------------------------------------------

def test_ps_quote_doubles_every_quote_like_character():
    assert wh.ps_quote("O'Brien") == "'O''Brien'"
    assert wh.ps_quote("a\u2019b") == "'a\u2019\u2019b'"
    assert wh.ps_quote("C:\\Users\\Tom&Jerry %TEMP%") == "'C:\\Users\\Tom&Jerry %TEMP%'"


def test_windows_command_line_keeps_inno_log_spelling():
    line = wh.windows_command_line(["/VERYSILENT", "/LOG=C:\\Users\\John Smith\\x.log", "a b"])
    assert line == '/VERYSILENT /LOG="C:\\Users\\John Smith\\x.log" "a b"'


@pytest.mark.parametrize("exe,expected", [
    ("C:\\Users\\a\\AppData\\Local\\Programs\\YazSes\\yazses-cli.exe",
     "C:\\Users\\a\\AppData\\Local\\Programs\\YazSes\\YazSesApp.exe"),
    ("C:\\Users\\a\\scoop\\apps\\yazses\\2.43.2\\YazSesApp.exe",
     "C:\\Users\\a\\scoop\\apps\\yazses\\current\\YazSesApp.exe"),
    ("C:\\Users\\a\\scoop\\apps\\yazses\\current\\yazses-cli.exe",
     "C:\\Users\\a\\scoop\\apps\\yazses\\current\\YazSesApp.exe"),
])
def test_relaunch_argv(exe, expected):
    assert wh.relaunch_argv(exe, True) == [expected, "--tray"]


def test_relaunch_is_unknown_outside_the_bundle():
    assert wh.relaunch_argv("C:\\Python312\\python.exe", False) is None


def test_arch_from_env_prefers_the_wow64_variable():
    assert wh.arch_from_env({"PROCESSOR_ARCHITECTURE": "x86", "PROCESSOR_ARCHITEW6432": "ARM64"}) == "arm64"
    assert wh.arch_from_env({"PROCESSOR_ARCHITECTURE": "AMD64"}) == "x64"


def _handoff(tmp_path, **kw):
    base = dict(
        kind="installer",
        argv=("C:\\T\\yazses-update\\YazSes-2.44.0-windows-x64.exe", "/VERYSILENT",
              "/LOG=C:\\T\\yazses update\\installer.log"),
        elevate=False, wait_pids=(11, 22),
        relaunch=("C:\\P\\YazSes\\YazSesApp.exe", "--tray"),
        log_file=tmp_path / "update.log", result_file=tmp_path / "exit-code.txt",
        cleanup=(Path("C:/T/yazses-update/YazSes-2.44.0-windows-x64.exe"),),
        sha256=SHA,
    )
    base.update(kw)
    return UpdateHandoff(**base)


def test_the_installer_script_waits_verifies_runs_records_and_relaunches(tmp_path):
    script = wh.build_script(_handoff(tmp_path))
    order = [
        "$pids = @(11, 22)",
        "Wait-Process -Id $id",
        "if ($still.Count -gt 0) {",
        "[Security.Cryptography.SHA256]::Create()",
        f"-ne '{SHA}'",
        "Start-Process -FilePath 'C:\\T\\yazses-update\\YazSes-2.44.0-windows-x64.exe'",
        "Set-Content -LiteralPath $result",
        "Remove-Item -LiteralPath",
        "Start-Process -FilePath 'C:\\P\\YazSes\\YazSesApp.exe' -ArgumentList '--tray'",
    ]
    positions = [script.index(token) for token in order]
    assert positions == sorted(positions)
    assert '/LOG="C:\\T\\yazses update\\installer.log"' in script
    assert "-Verb RunAs" not in script  # the installer elevates itself if it must
    # The relaunch is outside the try: it runs whether or not the update worked.
    assert script.index("} catch {") < script.rindex("Start-Process -FilePath 'C:\\P")


def test_choco_is_elevated_and_winget_is_captured(tmp_path):
    choco = wh.build_script(_handoff(tmp_path, kind="package-manager", sha256="", cleanup=(),
                                     argv=("choco", "upgrade", "yazses", "-y"), elevate=True))
    assert "$psi.Verb = 'runas'" in choco and "Get-FileHash" not in choco
    # A declined UAC prompt is recorded as such, not as "could not start".
    assert "NativeErrorCode -eq 1223" in choco and f"$code = {wh.EXIT_ELEVATION_DECLINED}" in choco
    assert "-Verb RunAs" not in choco and "$psi.WindowStyle" not in choco  # its console stays
    winget = wh.build_script(_handoff(tmp_path, kind="package-manager", sha256="", cleanup=(),
                                      argv=("winget", "upgrade", "--id", "MSKazemi.YazSes"),
                                      capture_output=True))
    assert "& 'winget' 'upgrade' '--id' 'MSKazemi.YazSes' 2>&1" in winget
    assert "Out-File -LiteralPath $log -Append" in winget


def test_encode_command_round_trips_unicode():
    script = "Write-Note 'C:\\Users\\محسن\\Müller'"
    decoded = base64.b64decode(wh.encode_command(script)).decode("utf-16-le")
    assert decoded == script


def test_hand_off_spawns_detached_powershell_by_absolute_path(tmp_path):
    calls = []
    launcher = wh.WindowsUpdateLauncher(
        env={"SystemRoot": "C:\\Windows"}, executable="C:\\P\\YazSesApp.exe", frozen=True,
        spawn=lambda argv, **kw: calls.append((argv, kw)), exists=lambda p: True,
    )
    launcher.hand_off(_handoff(tmp_path))
    (argv, kw), = calls
    assert argv[0] == "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    assert "-EncodedCommand" in argv and "-NoProfile" in argv
    assert kw["creationflags"] & wh._CREATE_BREAKAWAY_FROM_JOB
    assert kw["creationflags"] & wh._CREATE_NO_WINDOW
    assert kw["cwd"] == str(tmp_path)


def test_hand_off_retries_without_breakaway(tmp_path):
    flags = []

    def _spawn(argv, **kw):
        flags.append(kw["creationflags"])
        if kw["creationflags"] & wh._CREATE_BREAKAWAY_FROM_JOB:
            raise PermissionError("access denied")

    launcher = wh.WindowsUpdateLauncher(env={}, spawn=_spawn, exists=lambda p: True)
    launcher.hand_off(_handoff(tmp_path))
    assert len(flags) == 2 and not flags[1] & wh._CREATE_BREAKAWAY_FROM_JOB


def test_hand_off_without_powershell_raises_oserror(tmp_path):
    launcher = wh.WindowsUpdateLauncher(env={}, spawn=lambda *a, **k: None, exists=lambda p: False)
    with pytest.raises(OSError):
        launcher.hand_off(_handoff(tmp_path))


def test_the_windows_launcher_satisfies_the_protocol():
    assert isinstance(wh.WindowsUpdateLauncher(env={}), UpdateLauncher)
    assert isinstance(FakeLauncher(Path(".")), UpdateLauncher)


def test_platforms_default_to_no_launcher_and_windows_registers_one():
    import dataclasses

    field = {f.name: f for f in dataclasses.fields(Platform)}["update_launcher"]
    assert field.default is None
    source = (ROOT / "src/yazses/platform/windows/__init__.py").read_text(encoding="utf-8")
    assert "update_launcher=WindowsUpdateLauncher()" in source


# ---- the installer contract the hand-off relies on ----------------------------------

def test_the_inno_script_upgrades_in_place():
    iss = (ROOT / "packaging/windows/installer.iss").read_text(encoding="utf-8")
    # The AppId must never change — it is what makes the new installer an upgrade.
    assert "AppId={{F3E8B8A4-1B6C-4F24-9BE8-9B7E58E9C4A2}" in iss
    assert "PrivilegesRequired=lowest" in iss
    assert "CloseApplications=yes" in iss
    assert "*.pyd" in iss
    # The hand-off relaunches; a silent install must not start a second tray.
    run = iss.split("[Run]", 1)[1].split("[", 1)[0]
    assert "skipifsilent" in run
    assert "UsePreviousAppDir=no" not in iss and "UsePreviousPrivileges=no" not in iss


# ---- the CLI ------------------------------------------------------------------------

runner = CliRunner()


def _patch_cli(monkeypatch, tmp_path, status, *, result=None):
    import yazses.system.updater as updater
    import yazses.tray.updates as tray_updates

    monkeypatch.setattr(updater, "check_update", lambda current: status)
    monkeypatch.setattr(cli, "_update_launcher", lambda: FakeLauncher(tmp_path))
    monkeypatch.setattr(tray_updates, "update_wait_pids", lambda: [99])
    # Both read or act on the HOST: the developer's own tray holds tray.lock, and the
    # shutdown RPC would reach the developer's own daemon. Pinned for every CLI test.
    monkeypatch.setattr(cli, "_running_tray_pid", lambda: None)
    monkeypatch.setattr(cli, "_request_daemon_shutdown", lambda: None)
    started = []

    def _start(st, launcher, **kw):
        started.append((st, kw))
        return result or iu.HandoffResult(ok=True, title="Installing", message="closing now")

    monkeypatch.setattr(iu, "start_one_click_update", _start)
    return started


def test_cli_check_only_describes_the_one_click_path(monkeypatch, tmp_path):
    started = _patch_cli(monkeypatch, tmp_path, _status())
    out = runner.invoke(cli.app, ["update", "--check"])
    assert out.exit_code == 0, out.output
    assert "SHA256SUMS.txt" in out.output and "not code-signed" in out.output
    assert started == []


def test_cli_yes_hands_off_and_exits_zero(monkeypatch, tmp_path):
    started = _patch_cli(monkeypatch, tmp_path, _status())
    out = runner.invoke(cli.app, ["update", "--yes"])
    assert out.exit_code == 0, out.output
    assert len(started) == 1 and started[0][1]["wait_pids"] == [99]
    assert "closing now" in out.output


def test_cli_without_yes_asks_first(monkeypatch, tmp_path):
    started = _patch_cli(monkeypatch, tmp_path, _status())
    out = runner.invoke(cli.app, ["update"], input="n\n")
    assert out.exit_code == 0 and "Skipped" in out.output and started == []


def test_cli_failure_prints_manual_steps_and_exits_one(monkeypatch, tmp_path):
    failed = iu.HandoffResult(ok=False, title="x", message="The update was not installed: nope.",
                              steps=manual_update_steps("windows-installer"))
    _patch_cli(monkeypatch, tmp_path, _status(), result=failed)
    out = runner.invoke(cli.app, ["update", "--yes"])
    assert out.exit_code == 1
    assert "nope" in out.output and "releases" in out.output


def test_cli_package_manager_shows_its_command(monkeypatch, tmp_path):
    _patch_cli(monkeypatch, tmp_path, _status("choco", command=["choco", "upgrade", "yazses", "-y"]))
    out = runner.invoke(cli.app, ["update", "--check"])
    assert out.exit_code == 0
    assert "choco upgrade yazses -y --no-progress" in out.output
    assert "administrator" in out.output


# ---- the Windows tray click ----------------------------------------------------------

class _Icon:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def _tray_run(monkeypatch, tmp_path, status, *, confirm=True, result=None):
    import yazses.platform.windows.tray as wtray
    import yazses.tray.updates as tray_updates

    monkeypatch.setattr(tray_updates, "check_updates", lambda current=None: status)
    monkeypatch.setattr(tray_updates, "run_one_click",
                        lambda st, la, progress=None: result
                        or iu.HandoffResult(ok=True, title="Installing", message="bye"))
    opened = []
    monkeypatch.setattr(wtray, "open_link", lambda url: opened.append(url) or True)
    monkeypatch.setattr(wtray, "describe_update", lambda status=None: ("described", "body"))
    shown, icon = [], _Icon()
    wtray._run_update(icon, lambda _i, t, b: shown.append((t, b)),
                      launcher=FakeLauncher(tmp_path), confirm=lambda t, b: confirm,
                      sleep=lambda s: None)
    return shown, icon, opened


def test_tray_one_click_success_quits_so_the_installer_can_run(monkeypatch, tmp_path):
    shown, icon, opened = _tray_run(monkeypatch, tmp_path, _status())
    assert icon.stopped and shown[-1] == ("Installing", "bye") and opened == []


def test_tray_decline_installs_nothing(monkeypatch, tmp_path):
    shown, icon, _ = _tray_run(monkeypatch, tmp_path, _status(), confirm=False)
    assert not icon.stopped and "skipped" in shown[-1][1]


def test_tray_failure_keeps_running_and_opens_the_page(monkeypatch, tmp_path):
    failed = iu.HandoffResult(ok=False, title="Update not installed", message="nope")
    shown, icon, opened = _tray_run(monkeypatch, tmp_path, _status(), result=failed)
    assert not icon.stopped and opened == [RELEASES_URL]
    assert shown[-1][0] == "Update not installed"


def test_tray_without_one_click_keeps_the_old_behaviour(monkeypatch, tmp_path):
    shown, icon, _ = _tray_run(monkeypatch, tmp_path, _status("uv", command=["uv"]))
    assert shown == [("described", "body")] and not icon.stopped


# ==== review fixes (2026-10-20) =========================================================

# ---- 1. the DEFAULT opener sends the right headers per URL kind ------------------------
#
# Every test above injects an opener, so none of them ever saw the headers the real one
# builds -- which is how `Accept: application/octet-stream` went to api.github.com and
# came back HTTP 415, making every real one-click attempt fall back to manual.

class _CapturingOpener:
    def __init__(self, bodies):
        self.bodies = bodies
        self.requests = []
        self.handlers = None

    def open(self, req, timeout=None):
        self.requests.append((req, timeout))
        return _Resp(self.bodies[req.full_url])


def _capture_default_opener(monkeypatch, bodies):
    import urllib.request

    fake = _CapturingOpener(bodies)

    def _build(*handlers):
        fake.handlers = handlers
        return fake

    monkeypatch.setattr(urllib.request, "build_opener", _build)
    return fake


def test_the_default_opener_asks_the_api_for_json(monkeypatch):
    fake = _capture_default_opener(
        monkeypatch, {iu._RELEASES_API: json.dumps(_payload()).encode()})
    assert iu.fetch_release_payload()["tag_name"] == "v2.44.0"
    (req, _timeout), = fake.requests
    assert req.full_url == "https://api.github.com/repos/MSKazemi/yazses/releases/latest"
    assert req.get_header("Accept") == "application/vnd.github+json"
    assert req.get_header("X-github-api-version") == "2022-11-28"
    assert req.get_header("User-agent")
    assert any(isinstance(h, iu._GithubOnlyRedirects) for h in fake.handlers)


def test_the_default_opener_downloads_assets_as_octet_stream(monkeypatch, tmp_path):
    sums_url = f"{PREFIX}v2.44.0/SHA256SUMS.txt"
    asset = _plan()
    fake = _capture_default_opener(
        monkeypatch, {sums_url: _sums().encode(), asset.url: BLOB})
    assert SHA in iu.fetch_checksums(sums_url)
    iu.download_verified(asset, SHA, tmp_path)
    urls = [r.full_url for r, _ in fake.requests]
    assert urls == [sums_url, asset.url]
    for req, _ in fake.requests:
        assert req.get_header("Accept") == "application/octet-stream"
        assert req.get_header("X-github-api-version") is None


def test_request_headers_by_host():
    assert iu.request_headers(iu._RELEASES_API)["Accept"] == "application/vnd.github+json"
    assert iu.request_headers(f"{PREFIX}v1/x.exe")["Accept"] == "application/octet-stream"
    assert iu.request_headers("not a url")["Accept"] == "application/octet-stream"


# ---- 3. elevation: never a temp-folder installer; choco by absolute machine path -------

@pytest.mark.parametrize("scope,needle", [("unknown", "Could not tell"), ("", "Could not tell"),
                                          ("both", "Could not tell")])
def test_an_installer_install_whose_scope_is_unknown_is_not_offered(tmp_path, scope, needle):
    launcher = FakeLauncher(tmp_path, scope=scope)
    offer = iu.one_click_offer(_status(), launcher)
    assert offer is not None and not offer.ok and needle in offer.reason
    # The manual fallback says what to do and that nothing needs uninstalling, and it
    # fits the tray balloon whole (Windows drops a body over 255 chars).
    assert "releases page" in offer.reason and "no uninstall" in offer.reason
    from yazses.tray.about import fit_balloon

    body = f"YazSes 2.43.12 → 2.44.10\n{offer.reason}\nOpening the download page."
    assert fit_balloon(body) == body
    result = _run(launcher)
    assert not result.ok and launcher.handoffs == []
    assert any(RELEASES_URL in s for s in result.steps)


@pytest.mark.parametrize("sha", ["", "abc", "z" * 64])
def test_build_handoff_refuses_an_elevated_installer_without_a_hash(tmp_path, sha):
    with pytest.raises(iu.UpdateRefused):
        iu.build_handoff(kind="installer", argv=["x.exe"], elevate=True, capture_output=False,
                         wait_pids=[], relaunch=["a"], staging=tmp_path, sha256=sha)


@pytest.mark.parametrize("sha", ["", "abc", "z" * 64])
def test_build_script_refuses_an_elevated_installer_without_a_hash(tmp_path, sha):
    with pytest.raises(ValueError):
        wh.build_script(_handoff(tmp_path, elevate=True, sha256=sha))


def test_scope_for_matches_the_running_directory():
    app = "C:\\Users\\a\\AppData\\Local\\Programs\\YazSes"
    assert wh.scope_for(app, app + "\\", None) == "user"
    assert wh.scope_for(app.upper(), app, "C:\\Program Files\\YazSes") == "user"
    assert wh.scope_for("C:\\Program Files\\YazSes", app, "C:\\Program Files\\YazSes\\") == "machine"
    assert wh.scope_for(app, None, None) == "unknown"
    assert wh.scope_for(app, "D:\\Elsewhere", None) == "unknown"


def test_install_scope_reads_both_uninstall_keys():
    app = "C:\\Users\\a\\AppData\\Local\\Programs\\YazSes"
    seen = []

    def _reg(hive, subkey, names):
        seen.append((hive, subkey))
        return app + "\\" if hive == "HKEY_CURRENT_USER" else None

    launcher = wh.WindowsUpdateLauncher(env={}, executable=app + "\\YazSesApp.exe", frozen=True,
                                        registry=_reg)
    assert launcher.install_scope() == "user"
    assert {h for h, _ in seen} == {"HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"}
    assert all(k.endswith("{F3E8B8A4-1B6C-4F24-9BE8-9B7E58E9C4A2}_is1") for _, k in seen)
    assert wh.WindowsUpdateLauncher(env={}, frozen=False, registry=_reg).install_scope() == "unknown"


def test_chocolatey_is_resolved_from_the_machine_environment_only():
    present = {"D:\\choco\\choco.exe", "C:\\ProgramData\\chocolatey\\bin\\choco.exe"}
    exists = present.__contains__
    assert wh.chocolatey_exe("D:\\choco", exists) == "D:\\choco\\choco.exe"
    assert wh.chocolatey_exe("C:\\ProgramData\\chocolatey", exists) == \
        "C:\\ProgramData\\chocolatey\\bin\\choco.exe"
    # No machine variable, or an unexpanded one: NO fallback to the default directory.
    # %ProgramData% lets users create folders, so without a Chocolatey install to vouch
    # for C:\ProgramData\chocolatey a same-user process could plant choco.exe there.
    assert wh.chocolatey_exe(None, exists) is None
    assert wh.chocolatey_exe("", exists) is None
    assert wh.chocolatey_exe("%USERPROFILE%\\evil", exists) is None
    assert wh.chocolatey_exe("D:\\choco", lambda p: False) is None


def test_hand_off_runs_choco_by_absolute_path_never_from_the_user_env(tmp_path):
    calls = []
    reg = {("HKEY_LOCAL_MACHINE", "ChocolateyInstall"): "C:\\ProgramData\\chocolatey"}
    launcher = wh.WindowsUpdateLauncher(
        # A user-level variable pointing somewhere writable must be ignored.
        env={"SystemRoot": "C:\\Windows", "ChocolateyInstall": "C:\\Users\\a\\evil"},
        spawn=lambda argv, **kw: calls.append(argv),
        exists=lambda p: True,
        registry=lambda hive, sub, names: reg.get((hive, names[0])),
        which=lambda name: None,
    )
    handoff = _handoff(tmp_path, kind="package-manager", sha256="", cleanup=(),
                       argv=("choco", "upgrade", "yazses", "-y"), elevate=True)
    launcher.hand_off(handoff)
    script = base64.b64decode(calls[0][calls[0].index("-EncodedCommand") + 1]).decode("utf-16-le")
    assert "[Diagnostics.ProcessStartInfo]::new('C:\\ProgramData\\chocolatey\\choco.exe')" in script
    assert "$psi.Verb = 'runas'" in script and "evil" not in script


def test_hand_off_refuses_a_package_manager_it_cannot_find(tmp_path):
    launcher = wh.WindowsUpdateLauncher(env={}, spawn=lambda *a, **k: None,
                                        exists=lambda p: True, which=lambda n: None)
    handoff = _handoff(tmp_path, kind="package-manager", sha256="", cleanup=(),
                       argv=("scoop", "update", "yazses"), capture_output=True)
    with pytest.raises(OSError):
        launcher.hand_off(handoff)


# ---- 4. a package manager is offered only when its own feed has the version -----------

@pytest.mark.parametrize("method,text,expected", [
    ("choco", "Chocolatey v2.3.0\nyazses|2.44.0\n", "2.44.0"),
    ("choco", "YazSes|2.43.2", "2.43.2"),
    ("choco", "0 packages found.", None),
    ("winget", "Found YazSes [MSKazemi.YazSes]\nVersion: 2.44.0\nPublisher: MSKazemi\n", "2.44.0"),
    ("scoop", "Name        : yazses\nDescription : x\nVersion     : 2.43.2\nBucket : extras\n", "2.43.2"),
    ("scoop", "", None),
    ("scoop", None, None),
    ("pip", "Version: 9.9", None),
])
def test_parse_feed_version(method, text, expected):
    assert iu.parse_feed_version(method, text) == expected


@pytest.mark.parametrize("method", ["choco", "winget", "scoop"])
def test_a_lagging_feed_is_not_offered(tmp_path, method):
    lagging = {"choco": "yazses|2.43.2", "winget": "Version: 2.43.2",
               "scoop": "Version     : 2.43.2"}
    launcher = FakeLauncher(tmp_path, feed=lagging)
    offer = iu.one_click_offer(_status(method), launcher)
    assert offer is not None and not offer.ok
    assert "2.43.2" in offer.reason and "2.44.0" in offer.reason
    assert not _run(launcher, _status(method)).ok and launcher.handoffs == []


def test_an_unreadable_feed_is_not_offered(tmp_path):
    offer = iu.one_click_offer(_status("choco"), FakeLauncher(tmp_path, feed={}))
    assert offer is not None and not offer.ok and "Could not ask Chocolatey" in offer.reason


def test_a_caught_up_feed_is_offered(tmp_path):
    for method in ("choco", "winget", "scoop"):
        offer = iu.one_click_offer(_status(method), FakeLauncher(tmp_path))
        assert offer == iu.Offer(True)
    assert iu.one_click_offer(_status("uv"), FakeLauncher(tmp_path)) is None


def test_query_package_manager_runs_the_resolved_program(tmp_path):
    ran = []

    class _Proc:
        returncode = 0
        stdout = "yazses|2.44.0\n"
        stderr = ""

    # Without the machine-level ChocolateyInstall there is no choco to trust: nothing runs.
    bare = wh.WindowsUpdateLauncher(
        env={}, exists=lambda p: True, registry=lambda *a: None, which=lambda n: None,
        run=lambda argv, **kw: ran.append((argv, kw)) or _Proc(),
    )
    assert bare.query_package_manager("choco") is None and ran == []
    launcher = wh.WindowsUpdateLauncher(
        env={}, exists=lambda p: p.endswith("chocolatey\\choco.exe"),
        registry=lambda *a: "C:\\ProgramData\\chocolatey",
        which=lambda n: f"C:\\bin\\{n}.cmd",
        run=lambda argv, **kw: ran.append((argv, kw)) or _Proc(),
    )
    assert iu.parse_feed_version("choco", launcher.query_package_manager("choco")) == "2.44.0"
    assert ran[0][0][0] == "C:\\ProgramData\\chocolatey\\choco.exe"
    assert ran[0][1]["timeout"] and ran[0][1]["encoding"] == "utf-8"
    launcher.query_package_manager("scoop")
    assert ran[1][0] == ["C:\\bin\\scoop.cmd", "info", "yazses"]
    assert launcher.query_package_manager("pip") is None


def test_a_failing_feed_query_answers_none():
    class _Bad:
        returncode = 1
        stdout = "yazses|2.44.0"
        stderr = ""

    launcher = wh.WindowsUpdateLauncher(env={}, which=lambda n: "C:\\w.exe",
                                        run=lambda *a, **k: _Bad())
    assert launcher.query_package_manager("winget") is None

    def _boom(*a, **k):
        raise OSError("gone")

    launcher = wh.WindowsUpdateLauncher(env={}, which=lambda n: "C:\\w.exe", run=_boom)
    assert launcher.query_package_manager("winget") is None


# ---- 5. a process that will not exit aborts the install --------------------------------

def test_the_job_aborts_rather_than_force_closing(tmp_path):
    script = wh.build_script(_handoff(tmp_path))
    assert "/FORCECLOSEAPPLICATIONS" not in script
    abort = script.index("if ($still.Count -gt 0) {")
    run = script.index("Start-Process -FilePath 'C:\\T\\yazses-update")
    assert abort < run
    # The abort branch records its own code and the installer lives only in the else.
    between = script[abort:run]
    assert f"$code = {wh.EXIT_STILL_RUNNING}" in between and "} else {" in between
    assert f"AddSeconds({wh.WAIT_SECONDS})" in script
    # Cleanup and relaunch run on every path, after the branch closes.
    assert script.index("Remove-Item") > run and script.rindex("Start-Process") > run


def test_the_exit_codes_agree_between_the_job_and_the_report():
    assert (wh.EXIT_NOT_STARTED, wh.EXIT_HASH_MISMATCH, wh.EXIT_STILL_RUNNING) == \
        (iu.EXIT_NOT_STARTED, iu.EXIT_HASH_MISMATCH, iu.EXIT_STILL_RUNNING)
    _t, body = iu.describe_handoff_result({"from": "1.0", "to": "1.1"},
                                          str(iu.EXIT_STILL_RUNNING), "1.0")
    assert "did not finish closing" in body and "not run" in body


# ---- 6. MSIX is its own method, with no one-click ---------------------------------------

def test_msix_is_detected_from_the_host_fact():
    from yazses.system.updater import detect_install_method

    exe = "C:/Program Files/WindowsApps/MSKazemi.YazSes_2.44.0.0_x64__abc/YazSesApp.exe"
    assert detect_install_method(exe, frozen=True, choco=False, platform="win32",
                                 msix=True) == "msix"
    assert detect_install_method(exe, frozen=True, choco=False, platform="win32",
                                 msix=False) == "windows-installer"


def test_msix_gets_store_steps_and_no_one_click(tmp_path):
    from yazses.system.updater import GITHUB_METHODS, upgrade_command

    steps = manual_update_steps("msix")
    assert any("Store" in s for s in steps)
    assert not any("Download" in s for s in steps)
    assert upgrade_command("msix") is None and "msix" in GITHUB_METHODS
    assert iu.one_click_offer(_status("msix", steps=steps), FakeLauncher(tmp_path)) is None


def test_msix_click_does_not_open_the_exe_download_page():
    import yazses.tray.updates as tray_updates

    opened = []
    status = _status("msix", steps=manual_update_steps("msix"))
    _t, body = tray_updates.describe_update(status=status, opener=lambda u: opened.append(u) or True)
    assert opened == [] and "Store" in body


# ---- 8. single-flight lock ---------------------------------------------------------------

def test_the_lock_is_exclusive_and_goes_stale(tmp_path):
    import os

    first = iu.acquire_update_lock(tmp_path, now=lambda: 1000.0)
    assert first is not None and first.exists()
    os.utime(first, (1000.0, 1000.0))
    assert iu.acquire_update_lock(tmp_path, now=lambda: 1000.0 + 60) is None
    taken = iu.acquire_update_lock(tmp_path, now=lambda: 1000.0 + iu.LOCK_STALE_S + 1)
    assert taken == first


def test_a_second_click_while_one_runs_is_refused(tmp_path):
    launcher = FakeLauncher(tmp_path)
    (tmp_path / "stage").mkdir()
    held = iu.acquire_update_lock(tmp_path / "stage")
    assert held is not None
    result = _run(launcher)
    assert not result.ok and "already in progress" in result.message
    assert launcher.handoffs == [] and held.exists()  # the holder's lock is untouched


# ---- CLI: tray running, refused offers, graceful shutdown --------------------------------

def test_cli_waits_for_a_running_tray_instead_of_refusing(monkeypatch, tmp_path):
    # The tray autostarts at sign-in, so the old refusal made `yazses update` refuse
    # on nearly every Windows machine. The tray's PID is now waited for, and the
    # daemon is asked to stop only once the tray (which would respawn it) has gone.
    import time

    started = _patch_cli(monkeypatch, tmp_path, _status())
    holders = iter([4242, 4242, None])
    monkeypatch.setattr(cli, "_running_tray_pid", lambda: next(holders, None))
    monkeypatch.setattr(time, "sleep", lambda s: None)
    asked = []
    monkeypatch.setattr(cli, "_request_daemon_shutdown", lambda: asked.append(True))
    out = runner.invoke(cli.app, ["update", "--yes"])
    assert out.exit_code == 0, out.output
    assert started[0][1]["wait_pids"] == [99, 4242]
    assert "Waiting for the YazSes tray to close" in out.output
    assert "did not close" not in out.output
    assert asked == [True]


def test_cli_refuses_a_tray_it_cannot_identify(monkeypatch, tmp_path):
    started = _patch_cli(monkeypatch, tmp_path, _status())
    monkeypatch.setattr(cli, "_running_tray_pid", lambda: -1)
    out = runner.invoke(cli.app, ["update", "--yes"])
    assert out.exit_code == 1 and "could not be identified" in out.output and started == []


def test_cli_reports_a_refused_offer_without_installing(monkeypatch, tmp_path):
    started = _patch_cli(monkeypatch, tmp_path, _status("choco", command=["choco"]))
    monkeypatch.setattr(cli, "_update_launcher",
                        lambda: FakeLauncher(tmp_path, feed={"choco": "yazses|2.43.2"}))
    out = runner.invoke(cli.app, ["update", "--yes"])
    assert out.exit_code == 0 and "Chocolatey still offers 2.43.2" in out.output
    assert started == []


def test_cli_asks_the_daemon_to_shut_down_gracefully(monkeypatch, tmp_path):
    _patch_cli(monkeypatch, tmp_path, _status())
    monkeypatch.setattr(cli, "_running_tray_pid", lambda: None)
    asked = []
    monkeypatch.setattr(cli, "_request_daemon_shutdown", lambda: asked.append(True))
    out = runner.invoke(cli.app, ["update", "--yes"])
    assert out.exit_code == 0 and asked == [True]


def test_tray_refused_offer_explains_and_opens_the_page(monkeypatch, tmp_path):
    import yazses.platform.windows.tray as wtray
    import yazses.tray.updates as tray_updates

    monkeypatch.setattr(tray_updates, "check_updates", lambda current=None: _status())
    opened, shown, asked = [], [], []
    monkeypatch.setattr(wtray, "open_link", lambda url: opened.append(url) or True)
    wtray._run_update(_Icon(), lambda _i, t, b: shown.append((t, b)),
                      launcher=FakeLauncher(tmp_path, scope="unknown"),
                      confirm=lambda t, b: asked.append(1) or True, sleep=lambda s: None)
    assert asked == [] and opened == [RELEASES_URL]
    assert "Could not tell" in shown[-1][1]


# ---- a hand-off started outside the tray makes the tray close ----------------------------

def _pending(stage: Path, *, started: float, by_pid: int | None = 1, result: bool = False):
    stage.mkdir(parents=True, exist_ok=True)
    record: dict = {"from": "2.43.2", "to": "2.44.0", "started": started}
    if by_pid is not None:
        record["by_pid"] = by_pid
    (stage / iu.PENDING_NAME).write_text(json.dumps(record), encoding="utf-8")
    if result:
        (stage / iu.RESULT_NAME).write_text("0", encoding="utf-8")


def test_a_hand_off_by_another_process_after_the_tray_started_closes_it(tmp_path):
    _pending(tmp_path, started=200.0, by_pid=1)
    assert iu.handoff_started_elsewhere(tmp_path, since=100.0, own_pid=2) is True


@pytest.mark.parametrize("kwargs", [
    dict(started=50.0),               # older than this tray: the job relaunched it
    dict(started=200.0, by_pid=2),    # the tray's own click quits by itself
    dict(started=200.0, result=True),  # the job has already finished
])
def test_the_tray_stays_open_otherwise(tmp_path, kwargs):
    _pending(tmp_path, **kwargs)
    assert iu.handoff_started_elsewhere(tmp_path, since=100.0, own_pid=2) is False


def test_no_or_garbled_record_keeps_the_tray_open(tmp_path):
    assert iu.handoff_started_elsewhere(tmp_path, since=0.0, own_pid=1) is False
    (tmp_path / iu.PENDING_NAME).write_text("{not json", encoding="utf-8")
    assert iu.handoff_started_elsewhere(tmp_path, since=0.0, own_pid=1) is False
    (tmp_path / iu.PENDING_NAME).write_text('{"started": true}', encoding="utf-8")
    assert iu.handoff_started_elsewhere(tmp_path, since=0.0, own_pid=1) is False


def test_the_pending_record_names_the_process_that_started_it(tmp_path):
    import os

    result = _run(FakeLauncher(tmp_path))
    assert result.ok
    record = json.loads((tmp_path / "stage" / iu.PENDING_NAME).read_text(encoding="utf-8"))
    assert record["by_pid"] == os.getpid()


def test_the_tray_watch_is_inert_without_a_launcher_and_throttled_with_one(tmp_path):
    from yazses.tray.app import UpdateHandoffWatch

    assert UpdateHandoffWatch(None).should_close() is False

    clock = [0.0]
    launcher = FakeLauncher(tmp_path)
    watch = UpdateHandoffWatch(launcher, clock=lambda: clock[0], wall=lambda: 100.0,
                               own_pid=2, interval_s=1.0)
    assert watch.should_close() is False          # nothing handed off yet
    _pending(launcher.staging_dir(), started=150.0, by_pid=1)
    assert watch.should_close() is False          # throttled: it looked a moment ago
    clock[0] = 1.5
    assert watch.should_close() is True


def test_the_tray_poller_consults_the_watch_before_every_status_call():
    # Wired, not just written.
    import inspect

    import yazses.tray.app as tray_app

    src = inspect.getsource(tray_app.run)
    assert "UpdateHandoffWatch(getattr(platform, \"update_launcher\", None))" in src
    assert src.index("update_watch.should_close()") < src.index('client.call("status")')
    assert "tray.stop()" in src


def test_outside_the_tray_with_no_tray_asks_the_daemon_directly(tmp_path, monkeypatch):
    import yazses.tray.updates as tu

    monkeypatch.setattr(tu, "update_wait_pids", lambda: [10])
    seen, asked = [], []
    monkeypatch.setattr(iu, "start_one_click_update",
                        lambda st, la, **kw: seen.append(kw["wait_pids"])
                        or iu.HandoffResult(ok=True, title="t", message="m"))
    result = tu.hand_off_outside_tray(_status(), FakeLauncher(tmp_path), tray_pid=lambda: None,
                                      request_daemon_shutdown=lambda: asked.append(1))
    assert result.ok and seen == [[10]] and asked == [1]


def test_outside_the_tray_a_tray_that_never_closes_is_reported(tmp_path, monkeypatch):
    import yazses.tray.updates as tu

    monkeypatch.setattr(tu, "update_wait_pids", lambda: [10])
    monkeypatch.setattr(iu, "start_one_click_update",
                        lambda st, la, **kw: iu.HandoffResult(ok=True, title="t", message="m"))
    clock, said, asked = [0.0], [], []

    def _sleep(s):
        clock[0] += s

    result = tu.hand_off_outside_tray(
        _status(), FakeLauncher(tmp_path), tray_pid=lambda: 77,
        request_daemon_shutdown=lambda: asked.append(1),
        progress=lambda m, f: said.append(m), wait_s=2.0, sleep=_sleep, clock=lambda: clock[0],
    )
    assert result.ok and asked == [1]
    assert any("did not close" in m for m in said)


def test_outside_the_tray_a_failed_hand_off_stops_nothing(tmp_path, monkeypatch):
    import yazses.tray.updates as tu

    monkeypatch.setattr(tu, "update_wait_pids", lambda: [10])
    monkeypatch.setattr(iu, "start_one_click_update",
                        lambda st, la, **kw: iu.HandoffResult(ok=False, title="t", message="no"))
    asked = []
    result = tu.hand_off_outside_tray(_status(), FakeLauncher(tmp_path), tray_pid=lambda: 77,
                                      request_daemon_shutdown=lambda: asked.append(1))
    assert not result.ok and asked == []


# ---- 5. all-users installs: one UAC prompt, and nothing user-writable is trusted -------
#
# The elevated job copies the verified download into a fresh Administrators-only
# directory, hashes THAT copy against a SHA-256 written into its own -EncodedCommand
# text, and runs the copy. These tests pin the generated text; the Windows CI job
# (scripts/check_windows_update_handoff.py) runs it for real on a runner where UAC is
# off, and ADR-027's checklist covers the real prompt.

_PS_QUOTE_CHARS = ("'", "\u2018", "\u2019", "\u201a", "\u201b")
#: Everything that breaks a naively quoted PowerShell string.
HOSTILE = "C:\\Users\\O'Brien `$(calc) \u2018x\u2019 \u201ay\u201b \"z\" ;$env:X\\Temp\\yazses-update"
HOSTILE_NAME = "YazSes-2.44.0-windows-x64 O'B `$(calc) \u2019.exe"


def _ps_literals(script: str) -> tuple[list[str], str]:
    """Split PowerShell text into its single-quoted literals (decoded) and the code
    outside them, the way PowerShell's tokenizer reads single-quoted strings: any of
    the five quote characters opens or closes one, and two in a row inside one are a
    literal quote. An unterminated literal fails the test."""
    literals: list[str] = []
    code: list[str] = []
    i = 0
    while i < len(script):
        ch = script[i]
        if ch not in _PS_QUOTE_CHARS:
            code.append(ch)
            i += 1
            continue
        i += 1
        buf: list[str] = []
        while True:
            assert i < len(script), "unterminated single-quoted literal"
            ch = script[i]
            if ch in _PS_QUOTE_CHARS:
                if i + 1 < len(script) and script[i + 1] in _PS_QUOTE_CHARS:
                    buf.append(ch)
                    i += 2
                    continue
                i += 1
                break
            buf.append(ch)
            i += 1
        literals.append("".join(buf))
    return literals, "".join(code)


def _admin_handoff(tmp_path, *, source=None, sha=SHA, **kw):
    source = source or "C:\\T\\yazses-update\\YazSes-2.44.0-windows-x64.exe"
    base = dict(
        kind="installer",
        argv=(source, *iu.installer_arguments(all_users=True)),
        elevate=True,
        cleanup=(Path(source),),
        sha256=sha,
    )
    base.update(kw)
    return _handoff(tmp_path, **base)


def _elevated_from(outer: str) -> str:
    """The elevated script, decoded from the outer job's runas arguments."""
    literals, _code = _ps_literals(outer)
    args = next(lit for lit in literals if "-EncodedCommand" in lit)
    encoded = args.split("-EncodedCommand", 1)[1].strip()
    return base64.b64decode(encoded).decode("utf-16-le")


def _admin_script(name="YazSes-2.44.0-windows-x64.exe", source="C:\\T\\x.exe", sha=SHA):
    return wh.build_admin_install_script(source, sha, iu.installer_arguments(all_users=True),
                                         name)


# -- when the elevated path is offered (pure planning) --

def _registry(user=None, machine=None):
    def _reg(hive, subkey, names):
        return {"HKEY_CURRENT_USER": user, "HKEY_LOCAL_MACHINE": machine}[hive]

    return _reg


@pytest.mark.parametrize("user,machine,running,scope", [
    # Matches the HKLM uninstall entry: the all-users path.
    (None, "C:\\Program Files\\YazSes", "C:\\Program Files\\YazSes", "machine"),
    # Both entries exist (an old all-users install left behind): the running dir decides.
    ("C:\\Users\\a\\AppData\\Local\\Programs\\YazSes", "C:\\Program Files\\YazSes",
     "C:\\Program Files\\YazSes", "machine"),
    ("C:\\Users\\a\\AppData\\Local\\Programs\\YazSes", "C:\\Program Files\\YazSes",
     "C:\\Users\\a\\AppData\\Local\\Programs\\YazSes", "user"),
    # Running from neither: nothing is offered.
    (None, "C:\\Program Files\\YazSes", "D:\\Portable\\YazSes", "unknown"),
    (None, None, "C:\\Program Files\\YazSes", "unknown"),
])
def test_the_elevated_path_is_planned_only_for_an_hklm_uninstall_match(
        tmp_path, user, machine, running, scope):
    launcher = wh.WindowsUpdateLauncher(env={}, executable=running + "\\YazSesApp.exe",
                                        frozen=True, registry=_registry(user, machine))
    assert launcher.install_scope() == scope
    offer = iu.one_click_offer(_status(), launcher)
    assert offer is not None
    assert offer.ok is (scope != "unknown")
    assert offer.all_users is (scope == "machine")


def test_an_all_users_install_hands_off_an_elevated_copy_job(tmp_path):
    launcher = FakeLauncher(tmp_path, scope="machine")
    result = _run(launcher)
    assert result.ok, result.message
    (h,) = launcher.handoffs
    assert h.kind == "installer" and h.elevate and h.sha256 == SHA
    assert iu.ALL_USERS_SWITCH in h.argv and "/VERYSILENT" in h.argv
    # No /LOG: the elevated job writes nothing to a user-writable place.
    assert not any(a.startswith("/LOG") for a in h.argv)
    path = Path(h.argv[0])
    assert path.parent == launcher.staging_dir() and path in h.cleanup
    assert launcher.staging_dir() / iu.LOCK_NAME in h.cleanup


def test_a_per_user_install_is_never_elevated_and_never_gets_allusers(tmp_path):
    launcher = FakeLauncher(tmp_path, scope="user")
    assert _run(launcher).ok
    (h,) = launcher.handoffs
    assert not h.elevate and iu.ALL_USERS_SWITCH not in h.argv
    assert any(a.startswith("/LOG=") for a in h.argv)


def test_installer_arguments_per_scope(tmp_path):
    assert iu.installer_arguments(all_users=True) == [*iu.INSTALLER_SWITCHES, "/ALLUSERS"]
    assert iu.installer_arguments(tmp_path / "i.log")[-1] == f"/LOG={tmp_path / 'i.log'}"
    with pytest.raises(ValueError):
        iu.installer_arguments()


def test_inno_accepts_allusers_on_the_command_line():
    # /ALLUSERS has an effect only when PrivilegesRequiredOverridesAllowed allows the
    # command line; "dialog" implies it (Inno Setup help, PrivilegesRequiredOverridesAllowed).
    iss = (ROOT / "packaging" / "windows" / "installer.iss").read_text(encoding="utf-8")
    line = next(x for x in iss.splitlines() if x.startswith("PrivilegesRequiredOverridesAllowed="))
    assert {"dialog", "commandline"} & set(line.split("=", 1)[1].split())


def test_the_all_users_prompt_says_windows_will_ask_and_names_powershell():
    _t, text = iu.confirmation_prompt(_status(), all_users=True)
    assert iu.ALL_USERS_NOTE in text and "Windows PowerShell" in text
    _t, text = iu.confirmation_prompt(_status())
    assert iu.ALL_USERS_NOTE not in text


def test_the_tray_asks_with_the_all_users_note(monkeypatch, tmp_path):
    import yazses.platform.windows.tray as wtray
    import yazses.tray.updates as tray_updates

    monkeypatch.setattr(tray_updates, "check_updates", lambda current=None: _status())
    asked = []
    wtray._run_update(_Icon(), lambda _i, t, b: None,
                      launcher=FakeLauncher(tmp_path, scope="machine"),
                      confirm=lambda t, b: asked.append(b) or False, sleep=lambda s: None)
    assert len(asked) == 1 and iu.ALL_USERS_NOTE in asked[0]


def test_the_cli_check_says_windows_will_ask(monkeypatch, tmp_path):
    started = _patch_cli(monkeypatch, tmp_path, _status())
    monkeypatch.setattr(cli, "_update_launcher", lambda: FakeLauncher(tmp_path, scope="machine"))
    out = runner.invoke(cli.app, ["update", "--check"])
    assert out.exit_code == 0 and started == []
    assert iu.ALL_USERS_NOTE in " ".join(out.output.split())


# -- the outer (unelevated) job --

def test_the_outer_job_elevates_system_powershell_never_the_download(tmp_path):
    script = wh.build_script(_admin_handoff(tmp_path))
    _lits, code = _ps_literals(script)
    assert "[IO.Path]::Combine([Environment]::SystemDirectory, 'WindowsPowerShell'" in script
    assert "$psi.Verb = 'runas'" in script and "$psi.WindowStyle = 'Hidden'" in script
    # The downloaded file is hashed (a courtesy check) and deleted -- never started.
    temp = "C:\\T\\yazses-update\\YazSes-2.44.0-windows-x64.exe"
    assert f"Start-Process -FilePath '{temp}'" not in script
    assert f"ProcessStartInfo]::new('{temp}')" not in script
    assert "-Verb RunAs" not in script and "$env:" not in code


def test_the_outer_job_waits_elevates_records_cleans_and_relaunches_in_order(tmp_path):
    script = wh.build_script(_admin_handoff(tmp_path))
    order = [
        "Wait-Process -Id $id",
        "[Security.Cryptography.SHA256]::Create()",
        "$psi.Verb = 'runas'",
        "[Diagnostics.Process]::Start($psi)",
        "$p.WaitForExit()",
        "$code = $p.ExitCode",
        "Write-Note ('the update did not run: '",
        "Set-Content -LiteralPath $result",
        "Remove-Item -LiteralPath 'C:\\T\\yazses-update\\YazSes-2.44.0-windows-x64.exe'",
        "Start-Process -FilePath 'C:\\P\\YazSes\\YazSesApp.exe' -ArgumentList '--tray'",
    ]
    positions = [script.index(token) for token in order]
    assert positions == sorted(positions)


def test_a_declined_uac_prompt_is_recorded_and_yazses_still_relaunches(tmp_path):
    script = wh.build_script(_admin_handoff(tmp_path))
    declined = script.index("NativeErrorCode -eq 1223")
    assert f"$code = {wh.EXIT_ELEVATION_DECLINED}" in script[declined:declined + 200]
    # The decline throws to the job's catch, after which the result, the cleanup and the
    # relaunch all still run: they sit outside the try.
    assert declined < script.index("} catch {\r\n  Write-Note ('the update did not run: '")
    assert script.index("Set-Content -LiteralPath $result") > declined
    assert script.rindex("Start-Process -FilePath 'C:\\P\\YazSes\\YazSesApp.exe'") > declined
    described = iu.describe_handoff_result({"from": "2.43.2", "to": "2.44.0"},
                                           str(wh.EXIT_ELEVATION_DECLINED), "2.43.2")
    assert described is not None and "declined" in described[1]


def test_the_exit_codes_agree_between_the_two_modules():
    for name in ("EXIT_NOT_STARTED", "EXIT_HASH_MISMATCH", "EXIT_STILL_RUNNING",
                 "EXIT_ELEVATION_DECLINED", "EXIT_UNSAFE_STAGING"):
        assert getattr(iu, name) == getattr(wh, name), name
    assert len({iu.EXIT_NOT_STARTED, iu.EXIT_HASH_MISMATCH, iu.EXIT_STILL_RUNNING,
                iu.EXIT_ELEVATION_DECLINED, iu.EXIT_UNSAFE_STAGING}) == 5


@pytest.mark.parametrize("code,needle", [
    (iu.EXIT_ELEVATION_DECLINED, "administrator permission and it was declined"),
    (iu.EXIT_UNSAFE_STAGING, "only administrators can change"),
    (iu.EXIT_HASH_MISMATCH, "SHA-256"),
])
def test_the_next_start_explains_an_all_users_failure(code, needle):
    described = iu.describe_handoff_result({"from": "2.43.2", "to": "2.44.0"}, str(code), "2.43.2")
    assert described is not None and needle in described[1]


def test_the_outer_job_carries_exactly_the_elevated_script(tmp_path):
    handoff = _admin_handoff(tmp_path)
    elevated = _elevated_from(wh.build_script(handoff))
    assert elevated == wh.build_admin_install_script(
        handoff.argv[0], SHA, list(handoff.argv[1:]), "YazSes-2.44.0-windows-x64.exe")
    flags = wh.admin_install_command_line(handoff)
    assert flags.startswith("-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden")


def test_the_elevated_command_line_stays_within_a_budget(tmp_path):
    # ShellExecuteEx documents no limit on lpParameters, but older shells were reported
    # to fail near 2 K and CreateProcess caps a command line at 32 767 characters. A
    # deep, awkward path must still leave a wide margin; if this grows, measure it on
    # Windows before raising the number.
    deep = "C:\\Users\\" + "\u0645\u062d\u0633\u0646 O'B " * 12 + "\\AppData\\Local\\Temp\\yazses-update"
    handoff = _admin_handoff(tmp_path, source=deep + "\\YazSes-2.44.0-windows-x64.exe")
    assert len(wh.admin_install_command_line(handoff)) < 8000


def test_hand_off_starts_the_all_users_job_unelevated_through_the_same_spawn(tmp_path):
    calls = []
    launcher = wh.WindowsUpdateLauncher(
        env={"SystemRoot": "C:\\Windows"}, executable="C:\\Program Files\\YazSes\\YazSesApp.exe",
        frozen=True, spawn=lambda argv, **kw: calls.append(argv), exists=lambda p: True,
    )
    launcher.hand_off(_admin_handoff(tmp_path))
    (argv,) = calls
    assert argv[0] == "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    outer = base64.b64decode(argv[argv.index("-EncodedCommand") + 1]).decode("utf-16-le")
    assert "$psi.Verb = 'runas'" in outer and SHA in _elevated_from(outer)


# -- the elevated script itself --

def test_the_admin_only_acl_is_set_before_anything_is_copied():
    s = _admin_script()
    order = [
        "$PSModuleAutoLoadingPreference = 'None'",
        "[IO.Path]::GetDirectoryName([Environment]::SystemDirectory)",
        "[guid]::NewGuid()",
        "if ([IO.Directory]::Exists($dir)) { $dir = $null; throw",
        "[Security.AccessControl.DirectorySecurity]::new()",
        f"$acl.SetOwner([Security.Principal.SecurityIdentifier]::new('{wh.SID_ADMINISTRATORS}'))",
        "$acl.SetAccessRuleProtection($true, $false)",
        "$acl.AddAccessRule(",
        "[IO.Directory]::CreateDirectory($dir, $acl)",
        "[IO.Directory]::GetAccessControl($dir)",
        "-not $got.AreAccessRulesProtected",
        "GetFileSystemEntries($dir).Length -ne 0",
        "[IO.File]::Copy(",
    ]
    positions = [s.index(token) for token in order]
    assert positions == sorted(positions)
    # Exactly two principals, by SID, full control, inherited into the directory.
    assert f"@('{wh.SID_ADMINISTRATORS}', '{wh.SID_SYSTEM}')" in s
    assert "'FullControl', 'ContainerInherit, ObjectInherit', 'None', 'Allow'" in s
    assert s.count("AddAccessRule(") == 1  # inside the two-SID loop, nothing else
    assert "S-1-5-32-545" not in s and "S-1-1-0" not in s and "S-1-5-11" not in s  # Users, Everyone, Authenticated


def test_the_hash_compared_is_the_copy_s_and_the_expected_hash_is_a_literal():
    source = "C:\\Users\\a\\AppData\\Local\\Temp\\yazses-update\\YazSes-2.44.0-windows-x64.exe"
    s = _admin_script(source=source)
    literals, code = _ps_literals(s)
    assert SHA in literals                                  # a literal in the script itself
    assert literals.count(source) == 1                      # the download: named once...
    assert f"[IO.File]::Copy('{source}', $exe, $false)" in s  # ...as the copy's source only
    assert "$exe = [IO.Path]::Combine($dir, 'YazSes-2.44.0-windows-x64.exe')" in s
    assert "$held = [IO.File]::Open($exe, 'Open', 'Read', 'Read')" in s
    assert ".ComputeHash($held)" in s and "Get-FileHash" not in s
    assert s.index("[IO.File]::Copy(") < s.index("$held = [IO.File]::Open($exe")
    assert s.index(".ComputeHash($held)") < s.index(f"if ($hash -ne '{SHA}')")
    assert f"$code = {wh.EXIT_HASH_MISMATCH}; throw" in s


def test_the_installer_is_started_from_the_admin_only_dir_while_held_open():
    s = _admin_script()
    for line in ("$psi = [Diagnostics.ProcessStartInfo]::new($exe)",
                 "$psi.UseShellExecute = $false",
                 "$psi.WorkingDirectory = $dir",
                 "$psi.EnvironmentVariables['TEMP'] = $dir",
                 "$psi.EnvironmentVariables['TMP'] = $dir"):
        assert line in s
    assert "/ALLUSERS" in s and "/VERYSILENT" in s and "/LOG" not in s
    start = s.index("[Diagnostics.Process]::Start($psi)")
    assert s.index(f"if ($hash -ne '{SHA}')") < start < s.index("$held.Dispose()")
    assert s.count("::Start(") == 1


def test_the_admin_dir_is_deleted_on_every_exit_path():
    s = _admin_script()
    body, after = s.split("} finally {", 1)
    assert "[IO.Directory]::Delete($dir, $true)" in after and "$held.Dispose()" in after
    assert after.index("$held.Dispose()") < after.index("[IO.Directory]::Delete($dir, $true)")
    # One exit, after the finally: no path leaves the try without the cleanup.
    assert s.count("exit ") == 1 and s.rstrip().endswith("exit $code")
    assert "return" not in body
    # A pre-existing directory is not ours: forget it before throwing, never delete it.
    assert "if ([IO.Directory]::Exists($dir)) { $dir = $null; throw" in body
    # The default result is "unsafe staging" until the directory is verified, then
    # "not started" until the installer runs.
    assert body.index(f"$code = {wh.EXIT_UNSAFE_STAGING}") < body.index("throw 'unsafe directory'")
    assert body.index("throw 'unsafe directory'") < body.index(f"$code = {wh.EXIT_NOT_STARTED}")


def test_the_elevated_script_trusts_no_user_writable_input():
    s = _admin_script()
    _literals, code = _ps_literals(s)
    import re

    # No cmdlets at all (module auto-loading is off, and none is needed), no
    # environment reads, no profile, no writes to a user-writable place, no relaunch.
    assert not re.search(r"\b(Get|Set|New|Add|Remove|Start|Copy|Out|Write|Wait|Invoke|Test|"
                         r"Import|Move|Join|Split|Resolve)-[A-Z]", code), code
    assert "$env:" not in code and "Environment]::GetEnvironmentVariable" not in code
    assert "YazSesApp" not in s and "--tray" not in s


@pytest.mark.parametrize("bad", ["", "abc", "A" * 64, "g" * 64, SHA + "0"])
def test_the_elevated_script_needs_a_real_sha256(bad):
    with pytest.raises(ValueError):
        wh.build_admin_install_script("C:\\x.exe", bad, ["/VERYSILENT"], "x.exe")


@pytest.mark.parametrize("name", ["", ".", "..", "a\\b.exe", "a/b.exe", "..\\x.exe", 'a"b.exe',
                                  "c:x.exe", "a|b.exe"])
def test_the_elevated_script_refuses_a_name_that_is_not_a_plain_file_name(name):
    with pytest.raises(ValueError):
        wh.build_admin_install_script("C:\\x.exe", SHA, ["/VERYSILENT"], name)


def test_hostile_paths_are_quoted_everywhere_in_both_scripts(tmp_path):
    source = HOSTILE + "\\" + HOSTILE_NAME
    handoff = _admin_handoff(
        tmp_path, source=source,
        log_file=Path(HOSTILE) / "update.log", result_file=Path(HOSTILE) / "exit-code.txt",
        relaunch=(HOSTILE + "\\YazSesApp.exe", "--tray"),
    )
    outer = wh.build_script(handoff)
    elevated = _elevated_from(outer)
    for script in (outer, elevated):
        literals, code = _ps_literals(script)  # every literal terminates
        for marker in ("O'Brien", "`$(calc)", "calc", "\u2018", "\u2019", "\u201a", "\u201b",
                       "\"z\"", ";$env:X"):
            assert marker not in code, (marker, code)
    out_lits, _ = _ps_literals(outer)
    el_lits, _ = _ps_literals(elevated)
    assert source in out_lits and source in el_lits          # survived intact
    assert HOSTILE_NAME in el_lits                           # the copy's name too
    assert str(Path(HOSTILE) / "update.log") in out_lits


def test_no_hand_off_script_depends_on_get_filehash(tmp_path):
    """On windows-latest, Windows PowerShell 5.1 reported Get-FileHash "not recognized" in
    the unelevated job, so neither the per-user nor the all-users installer ever ran (run
    39577798547). Cause not confirmed: an inherited PowerShell 7 PSModulePath and an
    execution policy blocking 5.1's Utility .psm1 both fit. Every hash in every generated
    script, the elevated one included, is computed with .NET, which neither can block."""
    scripts = [
        wh.build_script(_handoff(tmp_path)),
        wh.build_script(_admin_handoff(tmp_path)),
        wh.build_admin_install_script("C:\\T\\YazSes-2.44.0-windows-x64.exe", SHA,
                                      ["/VERYSILENT"], "YazSes-2.44.0-windows-x64.exe"),
        wh.build_script(_handoff(tmp_path, kind="package-manager", sha256="", cleanup=(),
                                 argv=("choco", "upgrade", "yazses", "-y"), elevate=True)),
    ]
    for script in scripts:
        assert "Get-FileHash" not in script
    assert "[Security.Cryptography.SHA256]::Create()" in scripts[0]
    assert "$fs.Dispose()" in scripts[0]  # the installer is not held open while it runs
