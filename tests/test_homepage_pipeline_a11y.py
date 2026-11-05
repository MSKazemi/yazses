"""The homepage 'Architecture at a glance' pipeline can be paused and is not announced unprompted.

`docs/assets/landing.js` advances the nine-stage pipeline every 1.6 or 3.2 s. The detail
panel used to carry `aria-live="polite"` from the first byte, so a screen reader announced
every automatic update; there was no way to stop the loop (WCAG 2.2.2 Pause, Stop, Hide);
and keyboard focus paused it for good while the mouse resumed on leave. These static tests
pin the repaired contract: the visible text is never live, one permanent empty visually hidden
polite node is written to only on a person's own inspection, a real Pause button whose name
follows its state (Pause / Resume), real buttons for the stages, one shared hold helper for
hover and focus, and the reduced-motion guard. They read the source; the behaviour was probed
in a browser, and none of this was heard through a screen reader.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _arch_section() -> str:
    html = _read("overrides/home.html")
    match = re.search(r'<section class="yzl-arch".*?</section>', html, re.S)
    assert match, "overrides/home.html has no architecture section"
    return match.group(0)


def _pipeline_js() -> str:
    js = _read("docs/assets/landing.js")
    match = re.search(r"function pipeline\(root\) \{.*?\n  \}\n", js, re.S)
    assert match, "landing.js has no pipeline()"
    return match.group(0)


def _tags(html: str) -> list[str]:
    return re.findall(r"<[a-zA-Z][^>]*>", html)


def test_the_visible_detail_text_is_never_a_live_region_and_one_hidden_node_is() -> None:
    # Strip Jinja comments, which legitimately explain the design.
    section = re.sub(r"\{#.*?#\}", "", _arch_section(), flags=re.S)
    assert 'role="status"' not in section
    live = [t for t in _tags(section) if "aria-live" in t]
    # exactly one live node, and it is the permanent hidden announcer, not the visible text
    assert len(live) == 1 and "data-yzl-announce" in live[0]
    assert 'aria-live="polite"' in live[0] and "yzl-sr-only" in live[0]
    node = re.search(r"<div[^>]*data-yzl-announce[^>]*></div>", section)
    assert node, "the announce node must be empty in the markup (nothing is read unprompted)"

def test_markup_has_a_real_pause_button() -> None:
    button = next(t for t in _tags(_arch_section()) if "data-yzl-toggle" in t)
    assert button.startswith("<button")
    assert 'type="button"' in button
    # The name changes with the action (Pause -> Resume), so the button is NOT an aria-pressed
    # toggle: a pressed state beside a changing name reads as "Resume auto-advance, pressed".
    assert "aria-pressed" not in button
    assert 'data-state="running"' in button
    # Hidden until JS knows the loop can run: no dead control without JS or under reduced motion.
    assert " hidden" in button
    section = _arch_section()
    assert re.search(r"<span data-yzl-toggle-label>Pause auto-advance</span>", section)
    # The icon is decorative; the visible text is the accessible name.
    assert 'class="yzl-pipe__toggle-icon" aria-hidden="true"' in section

def test_announce_node_sits_outside_the_text_and_the_button() -> None:
    section = _arch_section()
    text = next(t for t in _tags(section) if "data-yzl-live" in t)
    assert "aria-live" not in text
    assert section.index("data-yzl-live") < section.index("data-yzl-desc") < section.index("data-yzl-announce")
    assert section.index("data-yzl-announce") < section.index("data-yzl-toggle")
    region = re.search(r'<div class="yzl-pipe__text" data-yzl-live>.*?</div>', section, re.S)
    assert region and "data-yzl-toggle" not in region.group(0) and "data-yzl-announce" not in region.group(0)

def test_js_writes_to_the_announce_node_only_when_not_auto_running() -> None:
    js = _pipeline_js()
    # the live region is permanent: JS never adds or removes the attribute any more
    assert "aria-live" not in re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    show = re.search(r"function show\(n, quiet\) \{.*?\n    \}\n", js, re.S)
    assert show, "pipeline() has no show(n, quiet)"
    assert "if (announce && !quiet && !running())" in show.group(0)
    sync = re.search(r"function sync\(\) \{.*?\n    \}\n", js, re.S)
    assert sync and "if (announce && running()) announce.textContent = \"\";" in sync.group(0)
    # the auto-advance step never touches the announce node, and the first paint is quiet
    loop = re.search(r"function loop\(\) \{.*?\n    \}\n", js, re.S)
    assert loop and "announce" not in loop.group(0)
    assert "show(0, true);" in js

def test_toggle_is_wired_and_its_name_follows_the_state() -> None:
    js = _pipeline_js()
    assert '"[data-yzl-toggle]"' in js
    assert "aria-pressed" not in re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    assert 'toggle.setAttribute("data-state", userPaused ? "paused" : "running")' in js
    assert '"Resume auto-advance" : "Pause auto-advance"' in js
    assert 'toggle.addEventListener("click"' in js
    assert "userPaused = !userPaused" in js
    css = _read("docs/assets/landing.css")
    assert 'aria-pressed' not in css
    assert '.yzl-pipe__toggle[data-state="paused"] .yzl-pipe__toggle-icon' in css

def test_hover_and_focus_share_one_hold_helper() -> None:
    js = _pipeline_js()
    assert "function hold(kind, on)" in js
    assert 'hold("hover", true)' in js and 'hold("hover", false)' in js
    assert 'hold("focus", true)' in js and 'hold("focus", false)' in js
    # the old inconsistent rule (a bare `paused` flag that only the mouse cleared) is gone
    assert not re.search(r"\bpaused\s*=\s*(true|false)", js)
    assert "mouseleave" not in js
    # leaving the pipeline by keyboard releases focus only when focus really leaves it
    assert "pipe.contains(e.relatedTarget)" in js
    # one rule decides whether the loop advances
    assert re.search(r"function loop\(\) \{\s*if \(running\(\)\)", js)


def test_reduced_motion_never_starts_the_loop_or_shows_the_button() -> None:
    js = _pipeline_js()
    running = re.search(r"function running\(\) \{.*?\n    \}\n", js, re.S)
    assert running and "!reduced" in running.group(0)
    assert "if (!reduced) timer = later(loop, 1600);" in js
    assert "if (!reduced) toggle.hidden = false;" in js
    css = _read("docs/assets/landing.css")
    block = re.search(r"@media \(prefers-reduced-motion: reduce\) \{.*?\n\}\n", css, re.S)
    assert block and ".yzl-pipe__toggle { display: none; }" in block.group(0)


def test_css_pulses_stop_when_paused_and_button_is_a_44px_target() -> None:
    css = _read("docs/assets/landing.css")
    assert re.search(
        r"\.yzl-pipe\.is-paused::after,\s*\.yzl-pipe\.is-paused \.yzl-stage--hot \.yzl-stage__icon \{ animation-play-state: paused; \}",
        css,
    )
    rule = re.search(r"\.yzl-pipe__toggle \{.*?\n\}", css, re.S)
    assert rule
    assert "min-height: 44px" in rule.group(0) and "min-width: 44px" in rule.group(0)
    assert ".yzl-pipe__toggle:focus-visible" in css
    assert "outline: none" not in rule.group(0)


def test_stages_are_list_items_holding_a_real_button_each() -> None:
    section = _arch_section()
    assert re.search(r'<ol class="yzl-pipe[^"]*" data-yzl-pipe role="list"', section)
    li = next(t for t in _tags(section) if t.startswith('<li class="yzl-stage'))
    # The <li> is not focusable (a tabindex with no role is a stop that says nothing): the
    # focusable, Enter/Space-operable element is the native <button> inside it.
    assert "tabindex" not in section
    assert "tabindex" not in li
    assert re.search(r'<li class="yzl-stage[^>]*>\s*(?:\{#.*?#\}\s*)?<button type="button" class="yzl-stage__btn" aria-label="', section, re.S)
    js = _pipeline_js()
    # focus lands on the button, so the handler listens for focusin on the <li>
    assert 's.addEventListener("focusin"' in js
    assert 's.addEventListener("focus"' not in js
    assert 'setAttribute("aria-current", "true")' in js