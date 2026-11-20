"""Guards for the device-free BCI HID parser under ``examples/bci-hid-switch/``.

The example is a research artifact for ADR-v2-157 (research record only; ADR-030 freezes
new device families). No BCI device exists in this repository, so these tests prove only
what synthetic bytes can prove: the report lengths agree with Apple's own example
descriptor, every report parses as Apple's reference lays it out, malformed input never
raises out of the decoder, the YazSes-side rules hold (baseline, toggle, quality floor,
pause), and the example is isolated from the product.

The module is loaded by path; the example folder is not put on ``sys.path``.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "bci-hid-switch"
ADR = ROOT / "design" / "adr" / "adr-v2-157-bci-hid-switch-consumer.md"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


bh = _load("_test_bci_hid_switch", EXAMPLE / "bcihid.py")

# Apple's Appendix descriptor, written out a second time as one hex string, independently
# of the module's byte list, so a typo in either one fails here.
APPLE_DESCRIPTOR_HEX = (
    "05600901a101"
    "056009028501a1020902150026ff00750895028106c0"
    "050909018502a1001901292015002501750195208102c0"
    "050109018503a1000930093109321581257f750895038106c0"
    "056009048504a1020904150026ff00750895018106c0"
    "0560a10285040903150026ff00750895069103c0"
    "c0"
)


# -- the layout agrees with Apple's descriptor -----------------------------------------


def test_the_module_descriptor_is_apples_byte_for_byte():
    assert bh.APPLE_EXAMPLE_DESCRIPTOR == bytes.fromhex(APPLE_DESCRIPTOR_HEX)
    assert len(bh.APPLE_EXAMPLE_DESCRIPTOR) == 119


def test_report_lengths_are_derived_from_the_descriptor_not_assumed():
    summary = bh.summarize_descriptor(bh.APPLE_EXAMPLE_DESCRIPTOR)
    assert (summary.top_usage_page, summary.top_usage) == (0x60, 0x01)
    derived = {key: summary.report_bytes(*key) for key in summary.report_bits}
    assert derived == bh.REPORT_LENGTHS


def test_input_and_output_report_4_share_an_id_in_opposite_directions():
    assert ("input", 4) in bh.REPORT_LENGTHS and ("output", 4) in bh.REPORT_LENGTHS
    assert bh.REPORT_ITEM_SELECTION == bh.REPORT_SCAN_INFO == 4


def test_a_device_is_recognised_by_its_usage_page_only():
    assert bh.is_bci_descriptor(bh.APPLE_EXAMPLE_DESCRIPTOR)
    mouse = bytes.fromhex("05010902a1010901a10005091901290315002501950375018102c0c0")
    assert not bh.is_bci_descriptor(mouse)
    assert not bh.is_bci_descriptor(b"")
    assert not bh.is_bci_descriptor(bytes.fromhex("0560"))  # no collection
    assert not bh.is_bci_descriptor(bytes.fromhex("0660"))  # truncated item
    assert not bh.is_bci_descriptor(bytes.fromhex("fe0201"))  # long item


def test_apple_action_vocabulary():
    assert len(bh.APPLE_ACTIONS) == 22 == len(set(bh.APPLE_ACTIONS))
    for needed in ("select", "toggle_dictation", "escape", "move_to_next_item"):
        assert needed in bh.APPLE_ACTIONS
    assert bh.APPLE_DEFAULT_BUTTONS == {0: "select", 1: "next", 2: "previous", 3: "menu"}


# -- parsing each report ---------------------------------------------------------------


def test_signal_quality_uses_apples_truncating_scale():
    assert bh.encode_signal_quality(2, 100) == bytes([1, 2, 255])
    assert bh.encode_signal_quality(2, 50) == bytes([1, 2, 127])  # 127.5 truncated
    assert bh.encode_signal_quality(0, 0) == bytes([1, 0, 0])
    assert bh.parse_input_report(bytes([1, 3, 200])) == bh.SignalQuality(3, 200)
    with pytest.raises(ValueError):
        bh.encode_signal_quality(0, 101)


@pytest.mark.parametrize("index", range(32))
def test_each_button_bit_is_little_endian_lsb_first(index):
    data = bh.encode_buttons([index])
    assert data[0] == 2 and len(data) == 5
    assert data[1 + index // 8] == 1 << (index % 8)  # Apple: byte i/8, mask 1 << i%8
    assert bh.parse_input_report(data).pressed() == {index}


def test_button_index_outside_0_31_is_refused_by_the_encoder():
    with pytest.raises(ValueError):
        bh.encode_buttons([32])


@pytest.mark.parametrize(
    ("raw", "dims"),
    [((5, -128, -128), 1), ((5, -3, -128), 2), ((5, -3, 0), 3), ((0, 0, 0), 3)],
)
def test_pointer_dimensionality_follows_the_valid_axes(raw, dims):
    data = bytes([3]) + bytes(v & 0xFF for v in raw)
    assert bh.parse_input_report(data).dimensions == dims


@pytest.mark.parametrize("raw", [(-128, 1, 1), (-128, -128, -128), (4, -128, 7)])
def test_pointer_shapes_apple_says_the_host_ignores_are_rejected(raw):
    data = bytes([3]) + bytes(v & 0xFF for v in raw)
    with pytest.raises(bh.ReportError) as err:
        bh.parse_input_report(data)
    assert err.value.reason == "pointer_shape"


def test_pointer_encoder_clamps_so_a_real_value_never_becomes_the_sentinel():
    assert bh.encode_pointer(-500, 500, -128) == bytes([3, 0x81, 0x7F, 0x81])
    assert bh.parse_input_report(bh.encode_pointer(-200)) == bh.Pointer(-127, None, None)


def test_item_selection_report():
    assert bh.parse_input_report(bh.encode_item_selection(255)) == bh.ItemSelection(255)


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"", "empty"),
        (bytes([9, 0]), "unknown_report_id"),
        (bytes([0, 0, 0]), "unknown_report_id"),
        (bytes([2, 0, 0, 0]), "bad_length"),
        (bytes([2, 0, 0, 0, 0, 0]), "bad_length"),
        (bytes([1, 0]), "bad_length"),
        (bytes([3, 0, 0, 0, 0]), "bad_length"),
    ],
)
def test_malformed_reports_name_their_reason(data, reason):
    with pytest.raises(bh.ReportError) as err:
        bh.parse_input_report(data)
    assert err.value.reason == reason


# -- host-to-device feedback -----------------------------------------------------------


def test_scan_info_round_trips_and_latency_is_int_plus_frac_over_255():
    data = bh.encode_scan_info(3, 12, 77, 1, 0.5, focus_is_keyboard_key=False)
    assert data == bytes([4, 3, 12, 77, 1, 0, 128])
    info = bh.parse_scan_info(data)
    assert (info.selected_item, info.number_of_items, info.seed, info.item_control_type) == (
        3, 12, 77, 1)
    assert info.latency_s == pytest.approx(128 / 255)


def test_scan_info_never_reveals_a_focused_keyboard_key():
    data = bh.encode_scan_info(9, 40, 5, 0, 1.25, focus_is_keyboard_key=True)
    assert data[1:5] == bytes(4)  # only the latency survives
    assert data[5:] == bytes([1, 64])


def test_scan_info_parser_is_strict():
    for bad in (b"", bytes([4] * 6), bytes([3, 0, 0, 0, 0, 0, 0])):
        with pytest.raises(bh.ReportError):
            bh.parse_scan_info(bad)


# -- the decoder's YazSes-side rules ---------------------------------------------------


def _feed(decoder, reports):
    events = []
    for n, data in enumerate(reports):
        events += decoder.feed(data, float(n))
    return events


def test_first_button_report_is_a_baseline_not_a_press():
    dec = bh.SwitchDecoder()
    assert _feed(dec, [bh.encode_buttons([1])]) == []
    assert dec.counts["baseline"] == 1


def test_next_becomes_a_press_tab_switch_press_and_repeats_are_idle():
    dec = bh.SwitchDecoder()
    events = _feed(dec, [bh.encode_buttons([]), bh.encode_buttons([1]),
                         bh.encode_buttons([1]), bh.encode_buttons([])])
    assert [(e.kind, e.detail["label"]) for e in events] == [("switch_press", "press tab")]
    assert events[0].channel == "bci-hid:button1"


def test_select_previous_and_menu_are_inert_by_default():
    dec = bh.SwitchDecoder()
    reports = [bh.encode_buttons([])]
    for i in (0, 2, 3):
        reports += [bh.encode_buttons([i]), bh.encode_buttons([])]
    assert _feed(dec, reports) == []
    assert dec.counts["unlabelled_action"] == 3


def test_unmapped_buttons_do_nothing():
    dec = bh.SwitchDecoder()
    assert _feed(dec, [bh.encode_buttons([]), bh.encode_buttons(range(4, 32))]) == []
    assert dec.counts["unmapped_button"] == 28


def test_toggle_dictation_flips_a_mode_on_press_edges_only():
    dec = bh.SwitchDecoder({5: "toggle_dictation"})
    click = [bh.encode_buttons([5]), bh.encode_buttons([])]
    events = _feed(dec, [bh.encode_buttons([]), *click, *click])
    assert [e.kind for e in events] == ["squeeze_on", "squeeze_off"]
    assert not dec.dictating


def test_low_signal_quality_refuses_the_press_and_unknown_quality_does_not():
    dec = bh.SwitchDecoder({0: "escape", 1: "next"})
    events = _feed(dec, [
        bh.encode_buttons([]),
        bh.encode_signal_quality(0, 10),  # 25 < 64: refuse button 0
        bh.encode_buttons([0, 1]),  # button 1 has no quality report: unknown, acts
    ])
    assert [e.detail["action"] for e in events] == ["next"]
    assert events[0].confidence == 1.0 and events[0].detail["quality"] is None
    assert dec.counts["refused_low_quality"] == 1


def test_quality_above_the_floor_becomes_the_event_confidence():
    dec = bh.SwitchDecoder({0: "escape"})
    events = _feed(dec, [bh.encode_buttons([]), bh.encode_signal_quality(0, 100),
                         bh.encode_buttons([0])])
    assert events[0].detail["label"] == "press escape"
    assert events[0].confidence == pytest.approx(1.0)


def test_the_floor_compares_against_the_raw_byte():
    dec = bh.SwitchDecoder({0: "escape"}, quality_floor=128)
    events = _feed(dec, [bh.encode_buttons([]), bytes([1, 0, 127]), bh.encode_buttons([0]),
                         bh.encode_buttons([]), bytes([1, 0, 128]), bh.encode_buttons([0])])
    assert len(events) == 1
    with pytest.raises(ValueError):
        bh.SwitchDecoder(quality_floor=256)


def test_release_all_closes_dictation_and_resets_the_baseline():
    dec = bh.SwitchDecoder({5: "toggle_dictation", 1: "next"})
    _feed(dec, [bh.encode_buttons([]), bh.encode_buttons([5])])
    assert dec.dictating
    closing = dec.release_all(9.0)
    assert [e.kind for e in closing] == ["squeeze_off"] and not dec.dictating
    # a button held across the pause is a baseline after it, not a press
    assert dec.feed(bh.encode_buttons([1]), 10.0) == []
    assert dec.release_all(11.0) == []


def test_pointer_and_item_selection_are_counted_never_acted_on():
    dec = bh.SwitchDecoder()
    assert _feed(dec, [bh.encode_pointer(3, 4), bh.encode_item_selection(2)]) == []
    assert dec.counts == {"pointer_ignored": 1, "item_selection_ignored": 1}


def test_decoder_rejects_bad_button_maps():
    with pytest.raises(ValueError):
        bh.SwitchDecoder({32: "select"})


@settings(max_examples=300, deadline=None)
@given(st.lists(st.binary(max_size=8), max_size=40))
def test_feed_never_raises_and_only_emits_known_kinds(chunks):
    dec = bh.SwitchDecoder({i: a for i, a in enumerate(
        ("select", "next", "escape", "toggle_dictation", "move_to_next_item"))})
    kinds = {e.kind for e in _feed(dec, chunks)}
    assert kinds <= {"squeeze_on", "squeeze_off", "switch_press"}


def test_run_refuses_a_device_that_is_not_usage_page_0x60():
    mouse = bytes.fromhex("05010902a1010901a10005091901290315002501950375018102c0c0")
    src = bh.ReplaySource([bh.encode_buttons([])], descriptor=mouse)
    with pytest.raises(bh.ReportError):
        bh.run(src, bh.SwitchDecoder())
    assert src.closed


def test_run_drains_a_replay_source_and_closes_it():
    src = bh.ReplaySource([bh.encode_buttons([]), bh.encode_buttons([1])])
    assert [e.kind for e in bh.run(src, bh.SwitchDecoder())] == ["switch_press"]
    assert src.closed


def test_cli_prints_events(capsys):
    assert bh.main(["0200000000", "0202000000"]) == 0
    assert "switch_press" in capsys.readouterr().out
    assert bh.main(["zz"]) == 2


# -- it fits the product's existing contracts (read, not changed) ----------------------


def test_events_are_shaped_like_bioevent_and_reuse_its_kinds():
    from yazses.biosignal.fprate import ACTIVATING_KINDS
    from yazses.biosignal.types import BioEvent, EventKind

    assert [f.name for f in dataclasses.fields(bh.SwitchEvent)] == [
        f.name for f in dataclasses.fields(BioEvent)]
    existing = {k.value for k in EventKind}
    assert {bh.KIND_MODE_ON, bh.KIND_MODE_OFF} <= existing
    assert {bh.KIND_MODE_ON, bh.KIND_MODE_OFF, bh.KIND_SWITCH_PRESS} <= (
        existing | bh.PROPOSED_KINDS)
    # SQUEEZE_ON is an activation the governor counts; SQUEEZE_OFF is a release
    assert EventKind(bh.KIND_MODE_ON) in ACTIVATING_KINDS
    assert EventKind(bh.KIND_MODE_OFF) not in ACTIVATING_KINDS


def test_every_default_label_is_a_command_the_grammar_already_parses():
    from yazses.commands.grammar import classify

    expected = {"press tab": "press_tab", "press escape": "press_escape"}
    for label in set(bh.DEFAULT_ACTION_LABELS.values()):
        assert classify(label).action == expected[label]
    assert "press enter" not in bh.DEFAULT_ACTION_LABELS.values()  # Enter is never a default


# -- isolation -------------------------------------------------------------------------


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_the_parser_imports_only_the_standard_library():
    imported = _imports(EXAMPLE / "bcihid.py")
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}
    forbidden = {"yazses", "socket", "ssl", "http", "urllib", "subprocess", "ctypes",
                 "fcntl", "hid", "hidapi", "evdev", "pywinusb", "pynput", "serial"}
    assert not imported & forbidden


def test_nothing_in_the_product_imports_the_example():
    needles = ("bci-hid-switch", "bci_hid_switch", "bcihid")
    sources = sorted((ROOT / "src").rglob("*.py"))
    assert len(sources) > 100
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not any(n in text for n in needles), path


def test_example_files_and_record_carry_no_ai_attribution():
    files = sorted(p for p in EXAMPLE.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts)
    assert [p.name for p in files] == ["README.md", "bcihid.py"]
    for path in [*files, ADR]:
        text = path.read_text(encoding="utf-8").lower()
        for needle in ("co-authored-by", "generated by", "generated with"):
            assert needle not in text, f"{path}: {needle}"


def test_the_record_cites_the_landing_page_and_stays_a_record():
    text = ADR.read_text(encoding="utf-8")
    assert ("https://developer.apple.com/documentation/accessibility/"
            "brain-computer-interface-hid-reference-for-connecting-to-apple-platforms") in text
    assert ".pdf" not in text
    assert "research record only" in text.lower()
