"""Local Voice Timer & Break Reminder (ADR-v2-093).

Set on-device timers/break reminders by voice, announced by read-back. The ``parse`` module is the
pure duration parser + command grammar; the daemon schedules the alert and TTS speaks it. OFF by
default.
"""
