"""The privacy panel on the General page: a thin Qt shell over ``privacy.py``."""
from __future__ import annotations

from typing import Any

from yazses.settingsui.context import PageContext
from yazses.settingsui.privacy import privacy_facts
from yazses.settingsui.widgets import button, card, label, restyle, row


def privacy_card(ctx: PageContext, data_dir: str) -> Any:
    frame, layout = card(hero=True)
    layout.addWidget(label("Privacy: what can leave this computer", heading=True))
    layout.addWidget(label(
        "Speech is recognised on this computer. These are facts from your saved "
        "settings, not switches.", muted=True,
    ))
    try:
        facts = privacy_facts(ctx.load_config())
    except Exception:  # noqa: BLE001 - a broken config must not stop the window
        layout.addWidget(label("The settings could not be read."))
        return frame
    for fact in facts:
        line = label(f"{fact.label}: {fact.value}\n{fact.detail}")
        if fact.leaves:
            restyle(line, level="warn")
        layout.addWidget(line)
    layout.addLayout(row(button("Open data folder", lambda: ctx.open_path(data_dir))))
    return frame
