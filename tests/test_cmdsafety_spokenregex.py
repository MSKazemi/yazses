"""Terminal Command Safety Gate (ADR-v2-065) + Spoken Regex Builder (ADR-v2-066) — pure cores."""
from __future__ import annotations

from yazses.cmdsafety.classify import ConfirmGate, assess_command
from yazses.spokenregex.build import nl_to_regex


# ---- command safety --------------------------------------------------------

def test_assess_dangerous():
    assert assess_command("rm -rf /home/me/stuff").level == "dangerous"
    assert assess_command("sudo dd if=/dev/zero of=/dev/sda").level == "dangerous"
    assert assess_command("mkfs.ext4 /dev/sdb1").level == "dangerous"
    assert assess_command("git push origin main --force").level == "dangerous"
    assert assess_command("curl https://x.sh | sudo bash").level == "dangerous"
    assert assess_command("git reset --hard HEAD~3").level == "dangerous"


def test_assess_caution_and_safe():
    assert assess_command("sudo apt update").level == "caution"
    assert assess_command("ls -la").level == "safe"
    assert assess_command("").level == "safe"


def test_assess_reason_present():
    a = assess_command("rm -rf /tmp/x")
    assert a.level == "dangerous" and a.reason


def test_confirm_gate_holds_then_releases():
    g = ConfirmGate()
    assert g.submit("echo hello") == "echo hello"          # safe passes through
    assert g.submit("rm -rf /data") is None                # dangerous held
    assert g.pending == "rm -rf /data"
    assert g.confirm() == "rm -rf /data"                   # released on confirm
    assert g.pending is None
    assert g.confirm() is None                             # nothing pending now


def test_confirm_gate_cancel():
    g = ConfirmGate()
    g.submit("mkfs /dev/sdb")
    g.cancel()
    assert g.pending is None


# ---- spoken regex ----------------------------------------------------------

def test_regex_counts_and_literals():
    assert nl_to_regex("four digits dash two digits") == r"\d{4}-\d{2}"
    assert nl_to_regex("three letters") == r"[A-Za-z]{3}"


def test_regex_quantifiers():
    assert nl_to_regex("one or more digits") == r"\d+"
    assert nl_to_regex("zero or more word characters") == r"\w*"
    assert nl_to_regex("optional dash") == r"-?"


def test_regex_anchor_and_class():
    assert nl_to_regex("lines starting with a capital letter") == r"^[A-Z]"
    assert nl_to_regex("any digit dot any digit") == r"\d\.\d"


def test_regex_none_when_empty():
    assert nl_to_regex("") is None
    assert nl_to_regex("hello world") is None


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "cmdsafety" in slugs and "spokenregex" in slugs
    assert Config().cmdsafety.enabled is False and Config().spokenregex.enabled is False
