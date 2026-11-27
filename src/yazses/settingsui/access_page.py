"""The Accessibility page: one switch card per capability in that category."""
from __future__ import annotations

from typing import Any

from yazses.settingsui.context import PageContext
from yazses.settingsui.widgets import button, label, page_widget, row

CATEGORY_PREFIX = "Accessibility"


class AccessibilityPage:
    def __init__(self, ctx: PageContext, groups: Any) -> None:
        self.widget, layout = page_widget()
        layout.addWidget(label(
            "Changes here are staged like on the Features page: click Apply to save them.",
            muted=True,
        ))
        layout.addLayout(row(button("Hands-free controls", lambda: ctx.goto("handsfree"))))
        for group in groups:
            if not group.category.startswith(CATEGORY_PREFIX):
                continue
            for item in group.rows:
                switch = ctx.switches.card(item.slug)
                if switch is not None:
                    layout.addWidget(switch)
        layout.addStretch(1)
