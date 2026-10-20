"""Run ADR-027's one-click Windows update for real, end to end, against a local release.

The unit tests in ``tests/test_one_click_windows_update.py`` prove the *decisions* and
the *text* of the PowerShell job. They cannot prove that Windows runs that job the way
the text says: every one of them injects the launcher, the opener or the spawn. The
first version of this feature passed all of them and could never have worked (the API
answered HTTP 415 to a header no test ever saw). This script is the evidence a test
double cannot give. On a Windows runner it uses:

* the real ``start_one_click_update``, ``download_verified`` and SHA-256 check, reading
  over a real socket from a fake GitHub served by ``http.server`` on 127.0.0.1 -- which,
  like GitHub, answers **415** to an API request without the JSON media type;
* the real ``WindowsUpdateLauncher``: the real HKCU uninstall-key read for the install
  scope, the real ``subprocess.Popen`` with the real creation flags, and the real
  ``powershell.exe -EncodedCommand`` job;
* a real ``.exe`` installer: a few lines of C# compiled with Windows PowerShell's own
  ``Add-Type``, which records its command line and start time and exits with a chosen
  code. The same program, copied to ``YazSesApp.exe``, records the relaunch, and a third
  copy plays a YazSes process that takes a few seconds to exit;
* paths with a space, an apostrophe and non-ASCII letters, for both the temp folder and
  the install directory (ADR-027 checklist item 10).

Scenarios: a good update (waits, re-hashes, runs the installer with the in-place switches,
records 0, relaunches); an installer that fails (its exit code is recorded, YazSes still
relaunches); a file tampered with after the download (hash mismatch, nothing runs,
relaunch); a YazSes process that will not exit (nothing runs, relaunch). Each result is
then read back by ``read_handoff_result``, the code the next tray start runs.

**All users** (needs an elevated session; GitHub's Windows runners are administrators
with UAC disabled, so ``runas`` elevates without a prompt): a real HKLM uninstall key, the
real ``runas`` start of System32's PowerShell with the elevated ``-EncodedCommand``, and
the fake installer recording *where* it ran -- ``<Windows>\\Temp\\yazses-update-<random>``,
with TEMP/TMP/working directory there, owner BUILTIN\\Administrators, a protected DACL
naming only Administrators and SYSTEM -- and that the directory is gone afterwards. Then
the elevated script is run directly with a matching and a wrong hash (exit -2, nothing
runs, the user-writable source untouched).

What it does NOT cover: DNS, TLS and GitHub's real redirects (the opener is pointed at
127.0.0.1); the real Inno installer; the UAC *prompt* (consent, decline, a standard user
entering admin credentials) and a filtered admin token that cannot write the directory;
a real tray and daemon. ADR-027's manual checklist still owns those.

Usage::

    uv run python scripts/check_windows_update_handoff.py            # Windows only
    uv run python scripts/check_windows_update_handoff.py --plan-only

``--plan-only`` runs on any OS: the fake release, the real fetch/download/verify and the
job's script text, with a recording launcher instead of PowerShell.

On Windows it writes the HKCU uninstall key the install-scope check reads. It refuses to
when that key already exists outside CI, so it can never clobber a real YazSes install.
"""
from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from yazses.system import installer_update as iu  # noqa: E402
from yazses.system.updater import UpdateStatus  # noqa: E402

CURRENT = "1.0.0"
TARGET = "1.0.1"
TAG = f"v{TARGET}"
ASSET = f"YazSes-{TARGET}-windows-x64.exe"
DOWNLOAD_PATH = f"/MSKazemi/yazses/releases/download/{TAG}/"
API_PATH = "/repos/MSKazemi/yazses/releases/latest"
#: A space, an apostrophe and non-ASCII letters: the characters that break quoting.
AWKWARD = "Yaz Ses 'é ü"

RECORD_ENV = "YAZSES_FAKE_RECORD_DIR"
EXIT_ENV = "YAZSES_FAKE_INSTALLER_EXIT"

#: The fake installer / app / lingering process. C# 5, so the .NET Framework compiler
#: behind Windows PowerShell 5.1's Add-Type accepts it.
FAKE_CS = r"""
using System;
using System.IO;
using System.Reflection;
using System.Security.AccessControl;
using System.Threading;

public static class FakeYazSes
{
    static string Rec(string name)
    {
        // An elevated child may not inherit the job's environment (the all-users path
        // runs the installer from a runas-started PowerShell), so there is a fixed
        // fallback the check also reads.
        string dir = Environment.GetEnvironmentVariable("YAZSES_FAKE_RECORD_DIR");
        if (string.IsNullOrEmpty(dir))
            dir = Path.Combine(Path.GetPathRoot(Environment.SystemDirectory), "yazses-handoff-records");
        return Path.Combine(dir, name);
    }

    static void RecordWhere()
    {
        // Where the installer runs from, its TEMP/TMP, and the ACL of its directory:
        // the all-users path must run it from an Administrators-only copy.
        string self = Assembly.GetEntryAssembly().Location;
        string dir = Path.GetDirectoryName(self);
        string sddl;
        try
        {
            sddl = Directory.GetAccessControl(dir).GetSecurityDescriptorSddlForm(
                AccessControlSections.Owner | AccessControlSections.Access);
        }
        catch (Exception e) { sddl = "error: " + e.Message; }
        File.WriteAllText(Rec("installer-where.txt"), self + "\n"
            + Environment.GetEnvironmentVariable("TEMP") + "\n"
            + Environment.GetEnvironmentVariable("TMP") + "\n"
            + Environment.CurrentDirectory + "\n" + sddl);
    }

    public static int Main(string[] args)
    {
        string ticks = DateTime.UtcNow.Ticks.ToString();
        if (args.Length >= 2 && args[0] == "--linger")
        {
            Thread.Sleep(int.Parse(args[1]) * 1000);
            File.WriteAllText(Rec("linger-exited.txt"), DateTime.UtcNow.Ticks.ToString());
            return 0;
        }
        if (args.Length >= 1 && args[0] == "--tray")
        {
            File.WriteAllText(Rec("relaunched.txt"), ticks + "\n" + Environment.CommandLine);
            return 0;
        }
        File.WriteAllText(Rec("installer.txt"), ticks + "\n" + Environment.CommandLine);
        RecordWhere();
        string code = Environment.GetEnvironmentVariable("YAZSES_FAKE_INSTALLER_EXIT");
        return string.IsNullOrEmpty(code) ? 0 : int.Parse(code);
    }
}
"""


# ---- a fake GitHub on 127.0.0.1 ----------------------------------------------------------

class FakeRelease:
    """Serves the release JSON, SHA256SUMS.txt and the installer, and records each request.

    The API route refuses a request whose ``Accept`` lacks ``application/vnd.github+json``
    with 415, as api.github.com does -- the defect that every injected-opener test missed.
    """

    def __init__(self, installer: bytes) -> None:
        self.installer = installer
        self.sha = hashlib.sha256(installer).hexdigest()
        self.requests: list[tuple[str, str]] = []
        sums = f"{'0' * 64}  yazses_{TARGET}_amd64.deb\n{self.sha}  {ASSET}\n".encode()
        self.routes: dict[str, bytes] = {
            DOWNLOAD_PATH + ASSET: installer,
            DOWNLOAD_PATH + iu.CHECKSUMS_ASSET: sums,
        }
        base = "https://github.com" + DOWNLOAD_PATH
        self.payload = {
            "tag_name": TAG,
            "draft": False,
            "prerelease": False,
            "assets": [
                {"name": ASSET, "browser_download_url": base + ASSET,
                 "size": len(installer), "digest": f"sha256:{self.sha}"},
                {"name": iu.CHECKSUMS_ASSET, "browser_download_url": base + iu.CHECKSUMS_ASSET,
                 "size": len(sums)},
            ],
        }
        release = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (http.server's spelling)
                accept = self.headers.get("Accept", "")
                release.requests.append((self.path, accept))
                if self.path == API_PATH:
                    if "application/vnd.github+json" not in accept:
                        self._send(415, b'{"message":"Unsupported Media Type"}')
                        return
                    self._send(200, json.dumps(release.payload).encode())
                    return
                body = release.routes.get(self.path)
                if body is None:
                    self._send(404, b"not found")
                    return
                self._send(200, body)

            def _send(self, code: int, body: bytes) -> None:
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: Any) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def open_url(self, url: str, timeout: float) -> Any:
        """``installer_update``'s ``open_url``, pointed at this server.

        The production headers (``request_headers``) are sent unchanged, so a wrong
        Accept header fails here exactly as it would against api.github.com.
        """
        parts = urllib.parse.urlsplit(url)
        local = f"http://127.0.0.1:{self.port}{parts.path}"
        request = urllib.request.Request(local, headers=iu.request_headers(url))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=timeout)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


# ---- checks -------------------------------------------------------------------------

class Checks:
    def __init__(self) -> None:
        self.failed: list[str] = []
        self.passed = 0

    def check(self, ok: bool, what: str, detail: str = "") -> None:
        if ok:
            self.passed += 1
            print(f"  PASS  {what}")
        else:
            self.failed.append(what)
            print(f"  FAIL  {what}" + (f"\n        {detail}" if detail else ""))


def _status() -> UpdateStatus:
    return UpdateStatus(method="windows-installer", current=CURRENT, latest=TARGET,
                        available=True, command=None, steps=["(manual steps)"])


def _one_click(release: FakeRelease, launcher: Any, wait_pids: list[int]) -> iu.HandoffResult:
    return iu.start_one_click_update(
        _status(),
        launcher,
        wait_pids=wait_pids,
        fetch_payload=lambda: iu.fetch_release_payload(open_url=release.open_url),
        fetch_sums=lambda url: iu.fetch_checksums(url, open_url=release.open_url),
        download=lambda asset, sha, dest, progress=None: iu.download_verified(
            asset, sha, dest, open_url=release.open_url, progress=progress),
    )


def check_requests(checks: Checks, release: FakeRelease) -> None:
    seen = dict(release.requests)
    checks.check("application/vnd.github+json" in seen.get(API_PATH, ""),
                 "the release API was asked for JSON (a 415 here was the original blocker)",
                 repr(release.requests))
    checks.check("application/octet-stream" in seen.get(DOWNLOAD_PATH + ASSET, ""),
                 "the installer was downloaded as octet-stream", repr(release.requests))


# ---- plan-only: any OS ------------------------------------------------------------------

class RecordingLauncher:
    def __init__(self, staging: Path, scope: str = "user") -> None:
        self.staging = staging
        self.scope = scope
        self.handoffs: list[Any] = []

    def staging_dir(self) -> Path:
        return self.staging

    def native_arch(self) -> str:
        return "x64"

    def relaunch_command(self) -> list[str]:
        return [rf"C:\Users\x\{AWKWARD}\YazSesApp.exe", "--tray"]

    def install_scope(self) -> str:
        return self.scope

    def query_package_manager(self, method: str) -> str | None:
        return None

    def hand_off(self, handoff: Any) -> None:
        self.handoffs.append(handoff)


def plan_only(work: Path) -> Checks:
    from yazses.platform.windows.update_handoff import build_script

    checks = Checks()
    release = FakeRelease(b"MZ" + b"\x00not a real installer\x00" * 64)
    try:
        launcher = RecordingLauncher(work / AWKWARD / "yazses-update")
        result = _one_click(release, launcher, [4242])
        checks.check(result.ok, "the one-click path reaches the hand-off", result.message)
        check_requests(checks, release)
        if launcher.handoffs:
            handoff = launcher.handoffs[0]
            staged = Path(handoff.argv[0])
            checks.check(staged.is_file() and hashlib.sha256(staged.read_bytes()).hexdigest()
                         == release.sha, "the staged installer is the verified download")
            script = build_script(handoff)
            for needle in ("Wait-Process", "Get-FileHash", "/VERYSILENT", "Set-Content",
                           "Start-Process -FilePath", "--tray"):
                checks.check(needle in script, f"the job script contains {needle}")
        _plan_all_users(checks, release, work)
    finally:
        release.close()
    return checks


def _plan_all_users(checks: Checks, release: FakeRelease, work: Path) -> None:
    """The all-users plan: an elevated job whose payload carries the hash and the copy."""
    import base64

    from yazses.platform.windows.update_handoff import build_script

    print("\n== all users (plan)")
    launcher = RecordingLauncher(work / AWKWARD / "machine" / "yazses-update", scope="machine")
    result = _one_click(release, launcher, [4242])
    checks.check(result.ok and len(launcher.handoffs) == 1,
                 "an all-users install reaches the hand-off", result.message)
    if not launcher.handoffs:
        return
    handoff = launcher.handoffs[0]
    checks.check(handoff.elevate and iu.ALL_USERS_SWITCH in handoff.argv,
                 "the hand-off is elevated and passes /ALLUSERS")
    script = build_script(handoff)
    checks.check("$psi.Verb = 'runas'" in script, "the job elevates through runas")
    encoded = script.split("-EncodedCommand ", 1)[1].split("'", 1)[0] if \
        "-EncodedCommand " in script else ""
    elevated = base64.b64decode(encoded).decode("utf-16-le") if encoded else ""
    for needle in (f"'{release.sha}'", "CreateDirectory($dir, $acl)", "[IO.File]::Copy(",
                   ".ComputeHash($held)", "[IO.Directory]::Delete($dir, $true)"):
        checks.check(needle in elevated, f"the elevated script contains {needle}")


# ---- Windows: the real thing ---------------------------------------------------------------

def compile_fake_exe(out: Path) -> None:
    """Compile ``FAKE_CS`` into a console ``.exe`` with Windows PowerShell's Add-Type."""
    from yazses.platform.windows.update_handoff import default_powershell

    source = out.with_suffix(".cs")
    source.write_text(FAKE_CS, encoding="utf-8")
    command = (
        f"Add-Type -Path '{source}' -OutputAssembly '{out}' "
        "-OutputType ConsoleApplication"
    )
    subprocess.run(
        [default_powershell(os.environ), "-NoProfile", "-NonInteractive", "-Command", command],
        check=True, timeout=180,
    )
    if not out.is_file():
        raise RuntimeError(f"Add-Type did not produce {out}")


class _Registry:
    """The Inno uninstall key ``install_scope`` reads, created for the run: HKCU for a
    per-user install, HKLM (administrators only) for an all-users one."""

    def __init__(self, app_dir: Path, in_ci: bool, hive: str = "HKEY_CURRENT_USER") -> None:
        import winreg  # type: ignore[import-not-found,unused-ignore]

        from yazses.platform.windows.update_handoff import UNINSTALL_SUBKEY

        self._winreg = winreg
        self._root = getattr(winreg, hive)
        self._subkey = UNINSTALL_SUBKEY
        try:
            winreg.CloseKey(winreg.OpenKey(self._root, UNINSTALL_SUBKEY))
            exists = True
        except OSError:
            exists = False
        if exists and not in_ci:
            raise SystemExit(
                f"YazSes's uninstall key already exists in {hive}: this machine has YazSes "
                "installed, and this check will not overwrite it. Run it in CI."
            )
        key = winreg.CreateKey(self._root, UNINSTALL_SUBKEY)
        winreg.SetValueEx(key, "Inno Setup: App Path", 0, winreg.REG_SZ, str(app_dir))
        winreg.CloseKey(key)

    def remove(self) -> None:
        try:
            self._winreg.DeleteKey(self._root, self._subkey)
        except OSError:
            pass


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _ticks(path: Path) -> int | None:
    try:
        return int(_read(path).splitlines()[0].strip())
    except (IndexError, ValueError):
        return None


def _expected_reason(installer_exit: int) -> str:
    """What ``describe_handoff_result`` says for an installer exit code (the version
    never moves here: the fake installer installs nothing)."""
    if installer_exit == 0:
        return "did not change the version"
    if installer_exit in (2, 5, 1223):
        return "cancelled"
    return f"exited with code {installer_exit}"


def _wait_for(predicate: Callable[[], bool], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.25)
    return predicate()


def run_windows(work: Path) -> Checks:
    from yazses.platform.windows import update_handoff as uh

    checks = Checks()
    build = work / "build"
    build.mkdir(parents=True)
    fake = build / "fake.exe"
    compile_fake_exe(fake)

    awkward = work / AWKWARD
    app_dir = awkward / "Programs" / "YazSes"
    app_dir.mkdir(parents=True)
    shutil.copy2(fake, app_dir / uh.APP_EXE)
    lingerer = build / "lingerer.exe"
    shutil.copy2(fake, lingerer)
    records = awkward / "records"
    records.mkdir()
    temp = awkward / "Temp"
    temp.mkdir()
    # The staging folder is %TEMP%\yazses-update; this makes %TEMP% awkward.
    tempfile.tempdir = str(temp)
    os.environ[RECORD_ENV] = str(records)

    spawned: list[subprocess.Popen] = []

    def _spawn(*args: Any, **kwargs: Any) -> subprocess.Popen:
        proc = subprocess.Popen(*args, **kwargs)  # the real Popen, real flags
        spawned.append(proc)
        return proc

    launcher = uh.WindowsUpdateLauncher(
        executable=str(app_dir / uh.APP_EXE), frozen=True, spawn=_spawn,
    )
    staging = launcher.staging_dir()
    release = FakeRelease(fake.read_bytes())
    registry = _Registry(app_dir, in_ci=os.environ.get("GITHUB_ACTIONS") == "true")
    try:
        checks.check(launcher.install_scope() == "user",
                     "the real HKCU uninstall key reads as a per-user install")
        checks.check(launcher.native_arch() in ("x64", "arm64"),
                     f"the machine architecture is read ({launcher.native_arch()})")

        def scenario(name: str, *, linger_s: int, installer_exit: int,
                     tamper: bool = False, wait_seconds: int | None = None) -> None:
            print(f"\n== {name}")
            for child in records.iterdir():
                child.unlink()
            os.environ[EXIT_ENV] = str(installer_exit)
            saved_wait = uh.WAIT_SECONDS
            if wait_seconds is not None:
                uh.WAIT_SECONDS = wait_seconds
            lingering = subprocess.Popen([str(lingerer), "--linger", str(linger_s)])
            spawned.clear()
            try:
                result = _one_click(release, launcher, [lingering.pid])
            finally:
                uh.WAIT_SECONDS = saved_wait
            checks.check(result.ok, "the hand-off started", result.message)
            if not result.ok:
                lingering.kill()
                return
            staged = staging / ASSET
            if tamper:
                data = bytearray(staged.read_bytes())
                data[-1] ^= 0xFF
                staged.write_bytes(bytes(data))
            job = spawned[0]
            try:
                job.wait(timeout=(wait_seconds or uh.WAIT_SECONDS) + 120)
            except subprocess.TimeoutExpired:
                job.kill()
                checks.check(False, "the PowerShell job finished")
            lingering.kill()
            lingering.wait(timeout=30)
            relaunched = _wait_for(lambda: (records / "relaunched.txt").exists(), 30)

            log = _read(staging / iu.LOG_NAME)
            code = _read(staging / iu.RESULT_NAME).strip()
            print("  update.log:\n    " + log.strip().replace("\n", "\n    "))
            installer = records / "installer.txt"
            expected = {"ok": str(installer_exit), "tamper": str(iu.EXIT_HASH_MISMATCH),
                        "stuck": str(iu.EXIT_STILL_RUNNING)}
            kind = "tamper" if tamper else "stuck" if wait_seconds is not None else "ok"
            checks.check(code == expected[kind], f"the job recorded exit code {expected[kind]}",
                         f"exit-code.txt says {code!r}")
            checks.check(relaunched, "YazSes was started again afterwards")
            relaunch_line = _read(records / "relaunched.txt")
            checks.check("--tray" in relaunch_line and AWKWARD in relaunch_line,
                         "the relaunch ran YazSesApp.exe --tray from the awkward path",
                         relaunch_line)
            checks.check(not staged.exists(), "the downloaded installer was deleted")
            checks.check(not (staging / iu.LOCK_NAME).exists(), "the update lock was released")
            if kind == "ok":
                started, exited = _ticks(installer), _ticks(records / "linger-exited.txt")
                checks.check(started is not None and exited is not None and started > exited,
                             "the installer started only after YazSes had exited",
                             f"installer {started}, YazSes exited {exited}")
                line = _read(installer)
                for switch in iu.INSTALLER_SWITCHES:
                    checks.check(switch in line, f"the installer got {switch}", line)
                log_arg = f'/LOG="{staging / iu.INSTALLER_LOG_NAME}"'
                checks.check(log_arg in line, "the installer got /LOG with the path quoted",
                             line)
                checks.check((_ticks(records / "relaunched.txt") or 0) >= (started or 0),
                             "the relaunch came after the installer")
            else:
                checks.check(not installer.exists(), "the installer was NOT run")
            report = iu.read_handoff_result(staging, CURRENT)
            checks.check(report is not None and report[0] == "Update did not install",
                         "the next start reads the result back", repr(report))
            needles = {"ok": _expected_reason(installer_exit),
                       "tamper": "SHA-256", "stuck": "did not finish closing"}
            checks.check(report is not None and needles[kind] in report[1],
                         f"and explains it ({needles[kind]!r})", repr(report))

        scenario("a good update", linger_s=4, installer_exit=0)
        check_requests(checks, release)
        scenario("an installer that fails", linger_s=1, installer_exit=1223)
        scenario("a download tampered with after the check", linger_s=5, installer_exit=0,
                 tamper=True)
        scenario("a YazSes process that does not exit", linger_s=60, installer_exit=0,
                 wait_seconds=3)
        registry.remove()
        run_windows_all_users(checks, work, fake, lingerer, release,
                              in_ci=os.environ.get("GITHUB_ACTIONS") == "true")
    finally:
        registry.remove()
        release.close()
    return checks


# ---- Windows, all users: the elevated admin-only-copy job --------------------------------

#: Where the fake installer records when the elevated job did not hand its environment on.
FALLBACK_RECORDS = "yazses-handoff-records"


def _is_admin() -> bool:
    try:
        import ctypes

        return bool(getattr(ctypes, "windll").shell32.IsUserAnAdmin())
    except Exception:
        return False


def _windows_temp() -> Path:
    return Path(os.environ.get("SystemRoot") or r"C:\Windows") / "Temp"


def _admin_dirs() -> set[Path]:
    from yazses.platform.windows.update_handoff import ADMIN_DIR_PREFIX

    try:
        return {p for p in _windows_temp().iterdir() if p.name.startswith(ADMIN_DIR_PREFIX)}
    except OSError:
        return set()


def parse_sddl(sddl: str) -> tuple[str, bool, set[str], bool]:
    """``(owner, dacl_protected, trustees, all_allow)`` from an ``O:..D:..`` SDDL string.

    ``O:BAD:P(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)`` -> ``("BA", True, {"BA", "SY"}, True)``.
    """
    import re

    owner = re.match(r"^O:(.*?)(?:G:|D:|$)", sddl)
    dacl = sddl.split("D:", 1)[1] if "D:" in sddl else ""
    flags = dacl.split("(", 1)[0]
    aces = re.findall(r"\(([^)]*)\)", dacl)
    trustees = {ace.split(";")[-1] for ace in aces if ace.count(";") == 5}
    return (owner.group(1) if owner else "", "P" in flags, trustees,
            bool(aces) and all(ace.startswith("A;") for ace in aces))


def _exit_code(raw: int) -> int:
    """A Windows exit code as the signed number the job wrote (-2, not 4294967294)."""
    return raw - (1 << 32) if raw >= (1 << 31) else raw


def _check_admin_copy_ran(checks: Checks, records: Path, before: set[Path]) -> None:
    from yazses.platform.windows.update_handoff import ADMIN_DIR_PREFIX

    where = _read(records / "installer-where.txt").splitlines()
    checks.check(len(where) >= 5, "the installer recorded where it ran", repr(where))
    if len(where) < 5:
        return
    exe, temp, tmp, cwd, sddl = where[0], where[1], where[2], where[3], "\n".join(where[4:])
    here = str(Path(exe).parent).rstrip("\\").casefold()
    prefix = str(_windows_temp() / ADMIN_DIR_PREFIX).casefold()
    checks.check(exe.casefold().startswith(prefix),
                 "the installer ran from <Windows>\\Temp\\yazses-update-<random>", exe)
    checks.check({temp.rstrip("\\").casefold(), tmp.rstrip("\\").casefold(),
                  cwd.rstrip("\\").casefold()} == {here},
                 "TEMP, TMP and the working directory were that same directory",
                 f"TEMP={temp} TMP={tmp} cwd={cwd}")
    owner, protected, trustees, all_allow = parse_sddl(sddl)
    checks.check(owner == "BA", "the directory is owned by BUILTIN\\Administrators", sddl)
    checks.check(protected, "the directory's DACL is protected (no inheritance)", sddl)
    checks.check(trustees == {"BA", "SY"} and all_allow,
                 "only Administrators and SYSTEM have access to it", sddl)
    checks.check(_admin_dirs() - before == set(), "the admin-only directory was deleted",
                 repr(sorted(_admin_dirs() - before)))


def _direct_elevated_runs(checks: Checks, work: Path, fake: Path, records: Path) -> None:
    """Run ``build_admin_install_script`` itself in this (elevated) session."""
    from yazses.platform.windows import update_handoff as uh

    source_dir = work / AWKWARD / "direct"
    source_dir.mkdir(parents=True)
    source = source_dir / ASSET
    shutil.copy2(fake, source)
    good = hashlib.sha256(source.read_bytes()).hexdigest()
    for label, sha, installer_exit, want in (
        ("a matching hash", good, 7, 7),
        ("a wrong hash", "0" * 64, 0, iu.EXIT_HASH_MISMATCH),
    ):
        print(f"\n== the elevated script, run directly, with {label}")
        for child in records.iterdir():
            child.unlink()
        before = _admin_dirs()
        script = uh.build_admin_install_script(
            str(source), sha, iu.installer_arguments(all_users=True), source.name)
        env = dict(os.environ, **{RECORD_ENV: str(records), EXIT_ENV: str(installer_exit)})
        proc = subprocess.run(uh.powershell_argv(uh.default_powershell(env), script),
                              env=env, timeout=180, check=False)
        code = _exit_code(proc.returncode)
        checks.check(code == want, f"it exited {want}", f"exit code {code}")
        ran = (records / "installer.txt").exists()
        checks.check(ran is (want == installer_exit),
                     "the copy ran" if want == installer_exit else "nothing ran")
        if ran:
            _check_admin_copy_ran(checks, records, before)
            line = _read(records / "installer.txt")
            checks.check(iu.ALL_USERS_SWITCH in line and "/LOG" not in line,
                         "the installer got /ALLUSERS and no /LOG", line)
        checks.check(_admin_dirs() - before == set(), "no admin-only directory was left behind")
        checks.check(source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest() == good,
                     "the user-writable source was only read, never changed")


def run_windows_all_users(checks: Checks, work: Path, fake: Path, lingerer: Path,
                          release: FakeRelease, in_ci: bool) -> None:
    """An all-users install end to end: offer → hand-off → runas → admin-only copy."""
    from yazses.platform.windows import update_handoff as uh

    print("\n== all users: the elevated update through an admin-only copy")
    if not _is_admin():
        # GitHub's Windows runners are administrators with UAC disabled, so runas
        # elevates without a prompt; anywhere else this half needs an elevated shell.
        checks.check(not in_ci, "the CI runner is elevated (GitHub: admin, UAC disabled)")
        print("  SKIP  not elevated; run from an administrator shell to cover all users")
        return
    records = Path(_windows_temp().anchor) / FALLBACK_RECORDS
    shutil.rmtree(records, ignore_errors=True)
    records.mkdir()
    saved_record = os.environ.get(RECORD_ENV)
    os.environ[RECORD_ENV] = str(records)
    app_dir = work / AWKWARD / "Program Files" / "YazSes"
    app_dir.mkdir(parents=True)
    shutil.copy2(fake, app_dir / uh.APP_EXE)
    spawned: list[subprocess.Popen] = []

    def _spawn(*args: Any, **kwargs: Any) -> subprocess.Popen:
        proc = subprocess.Popen(*args, **kwargs)
        spawned.append(proc)
        return proc

    launcher = uh.WindowsUpdateLauncher(executable=str(app_dir / uh.APP_EXE), frozen=True,
                                        spawn=_spawn)
    staging = launcher.staging_dir()
    registry = _Registry(app_dir, in_ci, hive="HKEY_LOCAL_MACHINE")
    before = _admin_dirs()
    lingering: subprocess.Popen | None = None
    try:
        checks.check(launcher.install_scope() == "machine",
                     "the real HKLM uninstall key reads as an all-users install")
        offer = iu.one_click_offer(_status(), launcher)
        checks.check(offer is not None and offer.ok and offer.all_users,
                     "an all-users install is offered, as all-users", repr(offer))
        os.environ[EXIT_ENV] = "0"
        lingering = subprocess.Popen([str(lingerer), "--linger", "2"])
        result = _one_click(release, launcher, [lingering.pid])
        checks.check(result.ok, "the all-users hand-off started", result.message)
        if not result.ok or not spawned:
            return
        try:
            spawned[0].wait(timeout=uh.WAIT_SECONDS + 180)
        except subprocess.TimeoutExpired:
            spawned[0].kill()
            checks.check(False, "the PowerShell job finished")
        relaunched = _wait_for(lambda: (records / "relaunched.txt").exists(), 30)
        log = _read(staging / iu.LOG_NAME)
        print("  update.log:\n    " + log.strip().replace("\n", "\n    "))
        code = _read(staging / iu.RESULT_NAME).strip()
        checks.check(code == "0", "the job recorded the elevated installer's exit code 0",
                     f"exit-code.txt says {code!r}")
        checks.check("administrator permission" in log, "the log says it asked for elevation")
        checks.check((records / "installer.txt").exists(), "the installer ran")
        _check_admin_copy_ran(checks, records, before)
        line = _read(records / "installer.txt")
        for switch in (*iu.INSTALLER_SWITCHES, iu.ALL_USERS_SWITCH):
            checks.check(switch in line, f"the installer got {switch}", line)
        checks.check("/LOG" not in line, "the elevated installer got no /LOG", line)
        checks.check(relaunched, "YazSes was started again afterwards")
        checks.check(not (staging / ASSET).exists(), "the downloaded installer was deleted")
        checks.check(not (staging / iu.LOCK_NAME).exists(), "the update lock was released")
        report = iu.read_handoff_result(staging, CURRENT)
        checks.check(report is not None and "did not change the version" in report[1],
                     "the next start reads the result back", repr(report))
        handoff_line = uh.admin_install_command_line(
            iu.build_handoff(kind="installer",
                             argv=[str(staging / ASSET), *iu.installer_arguments(all_users=True)],
                             elevate=True, capture_output=False, wait_pids=[],
                             relaunch=["x"], staging=staging, sha256=release.sha))
        print(f"  the elevated command line is {len(handoff_line)} characters")
        _direct_elevated_runs(checks, work, fake, records)
    finally:
        if lingering is not None:
            lingering.kill()
        registry.remove()
        for leftover in _admin_dirs() - before:
            shutil.rmtree(leftover, ignore_errors=True)
        shutil.rmtree(records, ignore_errors=True)
        if saved_record is None:
            os.environ.pop(RECORD_ENV, None)
        else:
            os.environ[RECORD_ENV] = saved_record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--plan-only", action="store_true",
                        help="stop at the hand-off (any OS); no PowerShell is run")
    args = parser.parse_args(argv)
    if not args.plan_only and sys.platform != "win32":
        print("This check runs the Windows hand-off; use --plan-only elsewhere.",
              file=sys.stderr)
        return 2
    saved_tempdir = tempfile.tempdir
    work = Path(tempfile.mkdtemp(prefix="yazses-handoff-"))
    try:
        checks = plan_only(work) if args.plan_only else run_windows(work)
    finally:
        tempfile.tempdir = saved_tempdir
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{checks.passed} passed, {len(checks.failed)} failed")
    for what in checks.failed:
        print(f"::error::Windows update hand-off: {what}")
    return 1 if checks.failed or not checks.passed else 0


if __name__ == "__main__":
    sys.exit(main())
