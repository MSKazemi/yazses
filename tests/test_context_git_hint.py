"""`[context] use_git`: project name and branch as recognition hints (ADR-v2-004).

All repositories here are synthetic: directories with hand-written ``.git`` files.
No ``git`` binary runs, which is also what the code under test promises.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from yazses.commands.context import ContextSources, compose_context_prompt
from yazses.commands.git_hint import GitHint, find_git, git_hint, hint_terms, read_branch
from yazses.config import Config, ContextConfig
from yazses.gitvoice.plan import despeak_ref, split_ref_words
from yazses.platform.base import FocusedCwdProvider, Platform

# --- fixtures -------------------------------------------------------------------------


def _repo(root: Path, head: str = "ref: refs/heads/main\n") -> Path:
    git = root / ".git"
    git.mkdir(parents=True)
    (git / "HEAD").write_text(head, encoding="utf-8")
    return root


# --- pure: finding the repository and reading HEAD -----------------------------------


def test_normal_repo(tmp_path):
    repo = _repo(tmp_path / "yazses", "ref: refs/heads/fix-tray-crash\n")
    assert git_hint(repo) == GitHint("yazses", "fix-tray-crash")


def test_branch_with_slash(tmp_path):
    repo = _repo(tmp_path / "proj", "ref: refs/heads/feature/login\n")
    assert git_hint(repo) == GitHint("proj", "feature/login")


def test_detached_head_keeps_name_drops_branch(tmp_path):
    repo = _repo(tmp_path / "proj", "3f1c2a9d8e7b6a5f4e3d2c1b0a9f8e7d6c5b4a39\n")
    assert git_hint(repo) == GitHint("proj", None)


def test_head_pointing_outside_heads_is_no_branch(tmp_path):
    repo = _repo(tmp_path / "proj", "ref: refs/remotes/origin/main\n")
    assert read_branch(repo / ".git") is None


def test_nested_directory_walks_up(tmp_path):
    repo = _repo(tmp_path / "proj", "ref: refs/heads/dev\n")
    deep = repo / "src" / "pkg" / "sub"
    deep.mkdir(parents=True)
    assert git_hint(deep) == GitHint("proj", "dev")


def test_file_start_uses_its_directory(tmp_path):
    repo = _repo(tmp_path / "proj")
    f = repo / "README.md"
    f.write_text("x", encoding="utf-8")
    assert git_hint(f) == GitHint("proj", "main")


def test_no_repo(tmp_path):
    plain = tmp_path / "plain" / "dir"
    plain.mkdir(parents=True)
    # tmp_path itself is outside any repo on CI; if a parent happens to be a repo the
    # answer must at least not be this directory's name.
    hint = git_hint(plain)
    assert hint is None or hint.repo_name not in {"plain", "dir"}
    assert git_hint(None) is None
    assert find_git(Path("relative/path")) is None


def test_linked_worktree_reads_its_own_head_and_main_name(tmp_path):
    main = _repo(tmp_path / "yazses", "ref: refs/heads/main\n")
    wt_git = main / ".git" / "worktrees" / "agent-1"
    wt_git.mkdir(parents=True)
    (wt_git / "HEAD").write_text("ref: refs/heads/feat/n4-context-git-hints\n", encoding="utf-8")
    (wt_git / "commondir").write_text("../..\n", encoding="utf-8")
    wt = tmp_path / "elsewhere" / "agent-1"
    wt.mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {wt_git}\n", encoding="utf-8")
    assert git_hint(wt) == GitHint("yazses", "feat/n4-context-git-hints")


def test_submodule_relative_gitdir(tmp_path):
    outer = _repo(tmp_path / "outer", "ref: refs/heads/main\n")
    mod_git = outer / ".git" / "modules" / "libfoo"
    mod_git.mkdir(parents=True)
    (mod_git / "HEAD").write_text("ref: refs/heads/topic\n", encoding="utf-8")
    sub = outer / "vendor" / "libfoo"
    sub.mkdir(parents=True)
    (sub / ".git").write_text("gitdir: ../../.git/modules/libfoo\n", encoding="utf-8")
    # The nearest .git wins: the submodule answers for itself.
    assert git_hint(sub) == GitHint("libfoo", "topic")


def test_broken_gitdir_pointer_is_none(tmp_path):
    d = tmp_path / "broken"
    d.mkdir()
    (d / ".git").write_text("gitdir: /does/not/exist\n", encoding="utf-8")
    assert git_hint(d) is None
    (d / ".git").write_text("not a pointer\n", encoding="utf-8")
    assert git_hint(d) is None


def test_oversized_head_is_ignored(tmp_path):
    repo = _repo(tmp_path / "proj", "ref: refs/heads/" + "a" * 10_000)
    assert git_hint(repo) == GitHint("proj", None)


# --- pure: terms ----------------------------------------------------------------------


def test_split_ref_words_uses_the_spoken_separator_table():
    assert split_ref_words("fix-tray-crash") == ["fix", "tray", "crash"]
    assert split_ref_words("feature/login_form.v2") == ["feature", "login", "form", "v2"]
    assert split_ref_words("") == []
    # Round trip with the spoken direction: each word joined by a spoken separator
    # de-speaks back to the branch.
    assert despeak_ref("fix dash tray dash crash") == "fix-tray-crash"


def test_hint_terms_name_branch_words():
    terms = hint_terms(GitHint("yazses", "fix-tray-crash"))
    assert terms == ["yazses", "fix-tray-crash", "fix", "tray", "crash"]


def test_hint_terms_drops_numbers_singletons_and_dupes():
    terms = hint_terms(GitHint("tray", "issue-123/a/Tray"))
    assert terms == ["tray", "issue-123/a/Tray", "issue"]


def test_hint_terms_caps_and_handles_none():
    assert hint_terms(GitHint("proj", "a-bb-cc-dd"), max_terms=2) == ["proj", "a-bb-cc-dd"]
    assert hint_terms(GitHint("proj", None)) == ["proj"]
    assert hint_terms(None) == []
    assert hint_terms(GitHint("proj", "x"), max_terms=0) == []


# --- composition ----------------------------------------------------------------------


def test_compose_includes_git_terms_only_with_use_git():
    src = ContextSources(window_title="Terminal", git_terms=["yazses", "tray", "crash"])
    assert "tray" not in compose_context_prompt(src)
    out = compose_context_prompt(src, use_git=True)
    assert "yazses" in out and "tray" in out and "crash" in out


def test_compose_git_terms_respect_max_terms():
    src = ContextSources(git_terms=[f"w{i}x" for i in range(10)])
    assert len(compose_context_prompt(src, use_git=True, max_terms=3).split(", ")) == 3


def test_config_key_is_dormant():
    assert ContextConfig().use_git is False
    assert ContextConfig(enabled=True).use_git is False


class _FakeCwd:
    def __init__(self, path):
        self._path = path

    def cwd(self):
        return self._path


def _daemon(tmp_path, *, enabled, use_git, cwd):
    from yazses.core.daemon import Daemon

    d = Daemon.__new__(Daemon)
    cfg = Config()
    cfg.context.enabled = enabled
    cfg.context.use_git = use_git
    cfg.context.use_window_title = False
    cfg.context.use_selection = False
    d._config = cfg
    d._platform = SimpleNamespace(
        paths=SimpleNamespace(config_file=tmp_path / "cfg" / "config.toml"),
        focused_cwd_factory=lambda: _FakeCwd(cwd),
    )
    d._personal_bias_terms = lambda: []  # type: ignore[method-assign]
    return d


@pytest.mark.parametrize(
    ("enabled", "use_git", "expected"),
    [(True, True, True), (True, False, False), (False, True, False), (False, False, False)],
)
def test_daemon_prompt_has_branch_words_only_when_both_on(
    tmp_path, monkeypatch, enabled, use_git, expected
):
    monkeypatch.delenv("YAZSES_VOCABULARY", raising=False)
    repo = _repo(tmp_path / "yazses", "ref: refs/heads/fix-tray-crash\n")
    d = _daemon(tmp_path, enabled=enabled, use_git=use_git, cwd=repo)
    prompt = d._effective_initial_prompt() or ""
    assert ("tray" in prompt and "crash" in prompt and "fix-tray-crash" in prompt) is expected


def test_daemon_survives_platform_without_provider(tmp_path, monkeypatch):
    monkeypatch.delenv("YAZSES_VOCABULARY", raising=False)
    d = _daemon(tmp_path, enabled=True, use_git=True, cwd=None)
    d._platform = SimpleNamespace(paths=d._platform.paths)  # no focused_cwd_factory
    assert "crash" not in (d._effective_initial_prompt() or "")


def test_daemon_survives_raising_provider(tmp_path, monkeypatch):
    monkeypatch.delenv("YAZSES_VOCABULARY", raising=False)
    d = _daemon(tmp_path, enabled=True, use_git=True, cwd=None)

    class Boom:
        def cwd(self):
            raise RuntimeError("/secret/path")

    d._platform.focused_cwd_factory = Boom
    assert d._git_hint_terms(48) == []


# --- platform seam --------------------------------------------------------------------


def test_fake_provider_satisfies_protocol(tmp_path):
    assert isinstance(_FakeCwd(tmp_path), FocusedCwdProvider)


def test_platform_field_defaults_to_none():
    import dataclasses

    fields = {f.name: f for f in dataclasses.fields(Platform)}
    assert fields["focused_cwd_factory"].default is None


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc is Linux")
def test_linux_reader_resolves_own_cwd(tmp_path, monkeypatch):
    from yazses.platform.linux.focused_cwd import LinuxFocusedCwd, process_cwd

    monkeypatch.chdir(tmp_path)
    assert process_cwd(os.getpid()) == Path(os.path.realpath(tmp_path))
    provider = LinuxFocusedCwd(pid_source=os.getpid)
    assert isinstance(provider, FocusedCwdProvider)
    # The pytest process may have children (xdist); it must still answer a directory.
    assert provider.cwd() is not None
    assert LinuxFocusedCwd(pid_source=lambda: None).cwd() is None
    assert process_cwd(2**22 + 12345) is None


def test_linux_reader_follows_youngest_descendant(tmp_path):
    from yazses.platform.linux.focused_cwd import focused_cwd

    proc = tmp_path / "proc"
    term_dir = tmp_path / "home"
    old_dir = tmp_path / "old"
    repo_dir = tmp_path / "repo"
    for d in (term_dir, old_dir, repo_dir):
        d.mkdir()

    def make(pid, cwd, start, children=()):
        p = proc / str(pid)
        (p / "task" / str(pid)).mkdir(parents=True)
        (p / "task" / str(pid) / "children").write_text(" ".join(map(str, children)), encoding="utf-8")
        fields = ["S"] + ["0"] * 18 + [str(start)] + ["0"] * 10
        (p / "stat").write_text(f"{pid} (a b) c) " + " ".join(fields), encoding="utf-8")
        os.symlink(cwd, p / "cwd")

    make(100, term_dir, 1, children=(200, 300))
    make(200, old_dir, 5)
    make(300, repo_dir, 9)  # started later: the tab the user just opened
    assert focused_cwd(100, proc) == repo_dir
    assert focused_cwd(200, proc) == old_dir
    assert focused_cwd(None, proc) is None


def test_linux_route_is_x11_only():
    from yazses.platform.linux import _focused_cwd_route

    assert _focused_cwd_route({"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}) is not None
    assert _focused_cwd_route({"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "w"}) is None
    assert _focused_cwd_route({}) is None
