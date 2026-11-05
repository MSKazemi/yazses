"""The homepage 'Architecture at a glance' pipeline can be paused and is not announced unprompted.

`docs/assets/landing.js` advances the nine-stage pipeline every 1.6 or 3.2 s. The detail
panel used to carry `aria-live="polite"` from the first byte, so a screen reader announced
every automatic update; there was no way to stop the loop (WCAG 2.2.2 Pause, Stop, Hide);
and keyboard focus paused it for good while the mouse resumed on leave. These static tests
pin the repaired contract: no live region in the markup, a real Pause button, one shared
hold helper for hover and focus, and the reduced-motion guard.
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


def test_markup_has_no_static_live_region() -> None:
    # Strip Jinja comments, which legitimately explain the absence.
    section = re.sub(r"\{#.*?#\}", "", _arch_section(), flags=re.S)
    assert "aria-live" not in section
    assert 'role="status"' not in section


def test_markup_has_a_real_pause_button() -> None:
    button = next(t for t in _tags(_arch_section()) if "data-yzl-toggle" in t)
    assert button.startswith("<button")
    assert 'type="button"' in button
    assert 'aria-pressed="false"' in button
    # Hidden until JS knows the loop can run: no dead control without JS or under reduced motion.
    assert " hidden" in button
    section = _arch_section()
    assert "Pause auto-advance" in section
    # The icon is decorative; the visible text is the accessible name.
    assert 'class="yzl-pipe__toggle-icon" aria-hidden="true"' in section


def test_detail_text_is_the_only_live_candidate() -> None:
    section = _arch_section()
    live = next(t for t in _tags(section) if "data-yzl-live" in t)
    assert "aria-live" not in live
    # the button sits outside the region that gets announced
    assert section.index("data-yzl-live") < section.index("data-yzl-desc") < section.index("data-yzl-toggle")
    region = re.search(r'<div class="yzl-pipe__text" data-yzl-live>.*?</div>', section, re.S)
    assert region and "data-yzl-toggle" not in region.group(0)


def test_js_adds_the_live_region_only_when_not_auto_running() -> None:
    js = _pipeline_js()
    assert 'removeAttribute("aria-live")' in js
    assert 'setAttribute("aria-live", "polite")' in js
    sync = re.search(r"function sync\(\) \{.*?\n    \}\n", js, re.S)
    assert sync, "pipeline() has no sync()"
    body = sync.group(0)
    # polite is set on the not-running branch, removed on the running branch
    assert re.search(r"if \(running\(\)\) live\.removeAttribute\(\"aria-live\"\);\s*else live\.setAttribute\(\"aria-live\", \"polite\"\)", body)
    # the auto-advance step itself never touches aria-live
    loop = re.search(r"function loop\(\) \{.*?\n    \}\n", js, re.S)
    assert loop and "aria-live" not in loop.group(0)


def test_toggle_is_wired_and_reflects_state() -> None:
    js = _pipeline_js()
    assert '"[data-yzl-toggle]"' in js
    assert 'setAttribute("aria-pressed"' in js
    assert 'toggle.addEventListener("click"' in js
    assert "userPaused = !userPaused" in js


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


def test_stage_items_keep_their_tab_order_and_gain_list_semantics() -> None:
    section = _arch_section()
    assert re.search(r'<ol class="yzl-pipe[^"]*" data-yzl-pipe role="list"', section)
    li = next(t for t in _tags(section) if t.startswith('<li class="yzl-stage'))
    assert 'tabindex="0"' in li  # no roving tabindex, no change to the keyboard model
    assert "tabindex=\"-1\"" not in section
    assert 'setAttribute("aria-current", "true")' in _pipeline_js()
