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

What it does NOT cover: DNS, TLS and GitHub's real redirects (the opener is pointed at
127.0.0.1); the real Inno installer; UAC; a real tray and daemon. ADR-027's manual
checklist still owns those.

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
using System.Threading;

public static class FakeYazSes
{
    static string Rec(string name)
    {
        return Path.Combine(Environment.GetEnvironmentVariable("YAZSES_FAKE_RECORD_DIR"), name);
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
    def __init__(self, staging: Path) -> None:
        self.staging = staging
        self.handoffs: list[Any] = []

    def staging_dir(self) -> Path:
        return self.staging

    def native_arch(self) -> str:
        return "x64"

    def relaunch_command(self) -> list[str]:
        return [rf"C:\Users\x\{AWKWARD}\YazSesApp.exe", "--tray"]

    def install_scope(self) -> str:
        return "user"

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
    finally:
        release.close()
    return checks


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
    """The HKCU Inno uninstall key ``install_scope`` reads, created for the run."""

    def __init__(self, app_dir: Path, in_ci: bool) -> None:
        import winreg  # type: ignore[import-not-found,unused-ignore]

        from yazses.platform.windows.update_handoff import UNINSTALL_SUBKEY

        self._winreg = winreg
        self._subkey = UNINSTALL_SUBKEY
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_SUBKEY))
            exists = True
        except OSError:
            exists = False
        if exists and not in_ci:
            raise SystemExit(
                "YazSes's uninstall key already exists in HKCU: this machine has YazSes "
                "installed, and this check will not overwrite it. Run it in CI."
            )
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_SUBKEY)
        winreg.SetValueEx(key, "Inno Setup: App Path", 0, winreg.REG_SZ, str(app_dir))
        winreg.CloseKey(key)

    def remove(self) -> None:
        try:
            self._winreg.DeleteKey(self._winreg.HKEY_CURRENT_USER, self._subkey)
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
    finally:
        registry.remove()
        release.close()
    return checks


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
