"""Voice-Controlled Window / Workspace Management (ADR-v2-070).

Hands-free desktop layout by voice. The ``commands`` module is the pure spoken-command grammar;
per-compositor backends (wmctrl/hyprctl/swaymsg/AppleScript/Win32) are deferred behind a
``windowctl`` extra. OFF by default.
"""
