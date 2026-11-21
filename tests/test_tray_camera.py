"""The tray's Camera toggle and held/released line (#924 items 3 and 4).

The menu decision is pure (`tray/camera.py`) and is tested on fake status payloads. The
daemon half is checked against a real `CameraSwitch`; the Qt/rumps/pystray shells are only
reached through their Qt-free seams, because none of the three is installable here.
"""
from __future__ import annotations

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.perception.switch import CameraConsumer, CameraSwitch
from yazses.platform import get_platform
from yazses.platform.base import TrayModel
from yazses.tray import camera as cam
from yazses.tray.controller import TrayController
from yazses.tray.menu import status_from_model


def _status(state="on", holders=(), failures=None, consumers=("facegesture",)):
    return {
        "camera": {
            "state": state,
            "holders": list(holders),
            "failures": dict(failures or {}),
            "consumers": list(consumers),
        }
    }


# ---------------------------------------------------------------- the pure entry


def test_on_and_held_is_checked_and_names_the_holders():
    entry = cam.camera_entry(_status(holders=("gaze", "head pointer")))
    assert entry is not None
    assert entry.label == "Camera"
    assert entry.checked is True
    assert entry.action == "off"
    assert entry.holders == ("gaze", "head pointer")
    assert entry.indicator == "Camera held by: gaze, head pointer"


def test_on_but_not_held_says_so():
    entry = cam.camera_entry(_status())
    assert entry is not None and entry.checked and "not held" in entry.indicator


def test_off_is_unchecked_released_and_a_click_turns_it_on():
    entry = cam.camera_entry(_status(state="off"))
    assert entry is not None
    assert entry.checked is False
    assert entry.action == "on"
    assert "released" in entry.indicator


def test_a_failed_reopen_is_named_in_the_line():
    entry = cam.camera_entry(_status(failures={"gaze": "busy"}))
    assert entry is not None and "gaze" in entry.indicator and entry.checked


def test_no_entry_without_a_camera_block_or_a_consumer():
    assert cam.camera_entry({}) is None  # an older daemon
    assert cam.camera_entry({"camera": None}) is None
    assert cam.camera_entry({"camera": "on"}) is None
    assert cam.camera_entry(_status(consumers=())) is None  # no camera feature enabled


def test_malformed_payload_does_not_raise():
    entry = cam.camera_entry(
        {"camera": {"state": "on", "holders": "gaze", "consumers": [1], "failures": []}}
    )
    assert entry is not None and entry.checked


# ---------------------------------------------------------------- the IPC call


class _Client:
    def __init__(self, reply=None, boom=None):
        self.calls = []
        self._reply, self._boom = reply, boom

    def call(self, method, **params):
        self.calls.append((method, params))
        if self._boom:
            raise self._boom
        return self._reply if self._reply is not None else {"ok": True}


def test_call_camera_sends_the_camera_method():
    client = _Client()
    assert cam.call_camera("off", client=client) == {"ok": True}
    assert client.calls == [("camera", {"action": "off"})]


def test_unreachable_daemon_is_a_refusal_shaped_reply_not_an_exception():
    reply = cam.call_camera("on", client=_Client(boom=OSError("gone")))
    assert reply["ok"] is False and "gone" in reply["reason"]


def test_describe_passes_the_daemon_words_through():
    assert cam.describe("on", {"ok": False, "reason": "nope"}) == ("YazSes", "nope")
    assert cam.describe("on", {"ok": False, "error": "dead"}) == ("YazSes", "dead")
    assert "released" in cam.describe("off", {"ok": True})[1]
    title, body = cam.describe("on", {"ok": True, "failures": {"gaze": "busy"}})
    assert body.startswith("Camera on.") and "gaze: busy" in body


def test_run_camera_action_end_to_end_with_a_fake_client():
    client = _Client(reply={"ok": True, "state": "off"})
    title, body = cam.run_camera_action("off", client=client)
    assert title == "YazSes" and "released" in body


def test_controller_set_camera_calls_the_camera_method():
    client = _Client()
    ctrl = TrayController(client)
    ctrl.set_camera(False)
    ctrl.set_camera(True)
    assert client.calls == [("camera", {"action": "off"}), ("camera", {"action": "on"})]


# ---------------------------------------------------------------- the bridge


def test_status_bridge_carries_the_camera_block():
    block = _status(holders=("gaze",))["camera"]
    assert status_from_model(TrayModel(camera=block))["camera"] == block
    assert status_from_model(TrayModel())["camera"] is None


# ---------------------------------------------------------------- the daemon


def test_daemon_status_payload_follows_the_switch_and_feeds_the_menu():
    d = Daemon(config=Config(), platform=get_platform())
    held = {"on": True}
    d._camera_switch.register(
        CameraConsumer(
            "gaze",
            pause=lambda: held.update(on=False),
            resume=lambda: held.update(on=True),
            holders=lambda: ("gaze",) if held["on"] else (),
        )
    )
    on = {"camera": d._camera_status_payload()}
    entry = cam.camera_entry(on)
    assert entry is not None and entry.checked and entry.holders == ("gaze",)

    d._camera_switch.set(False)
    off = cam.camera_entry({"camera": d._camera_status_payload()})
    assert off is not None and not off.checked and off.holders == ()


def test_daemon_status_payload_is_none_when_the_switch_raises():
    d = Daemon(config=Config(), platform=get_platform())

    class _Broken:
        def status(self):
            raise RuntimeError("x")

    d._camera_switch = _Broken()  # type: ignore[assignment]
    assert d._camera_status_payload() is None


def test_switch_subscribe_drives_a_tray_refresh():
    switch = CameraSwitch()
    seen: list[bool] = []
    switch.subscribe(seen.append)
    switch.set(False)
    assert seen == [False]


# ---------------------------------------------------------------- the platform shells
# The Windows menu runs against a stand-in pystray (see test_tray_windows_meeting_menu.py);
# the macOS helper is module-level so it needs no rumps. Qt and a real Mac menu are UNVERIFIED.


def test_macos_apply_camera_shows_and_hides_the_two_items():
    from types import SimpleNamespace

    from yazses.platform.macos import tray as mac_tray

    toggle = SimpleNamespace(hidden=True, state=0)
    line = SimpleNamespace(hidden=True, title="")
    entry = cam.camera_entry(_status(holders=("gaze",)))
    mac_tray._apply_camera([toggle, line], entry)
    assert (toggle.hidden, toggle.state, line.hidden) == (False, 1, False)
    assert line.title == "Camera held by: gaze"
    mac_tray._apply_camera([toggle, line], cam.camera_entry(_status(state="off")))
    assert toggle.state == 0
    mac_tray._apply_camera([toggle, line], None)
    assert toggle.hidden and line.hidden


def test_windows_menu_has_a_checked_toggle_and_a_line(monkeypatch):
    import sys
    import types

    from yazses.platform.windows import tray as win_tray

    class Item:
        def __init__(self, text, action=None, enabled=True, visible=True, checked=None):
            self._text, self.action, self._v, self._c = text, action, visible, checked

        def _r(self, x):
            return x(self) if callable(x) else x

        text = property(lambda self: self._r(self._text))
        visible = property(lambda self: self._r(self._v))
        checked = property(lambda self: self._r(self._c))

    class Menu:
        SEPARATOR = Item("-")

        def __init__(self, *items):
            self.items = items

    class Icon:
        last = None

        def __init__(self, name, image, title, menu):
            self.menu, self.icon, self.title = menu, image, title
            self.updates = 0
            Icon.last = self

        def run(self, setup=None):
            pass

        def update_menu(self):
            self.updates += 1

    fake = types.ModuleType("pystray")
    fake.Menu, fake.MenuItem, fake.Icon = Menu, Item, Icon
    monkeypatch.setitem(sys.modules, "pystray", fake)
    monkeypatch.setattr(win_tray, "_make_icon", lambda colour: object())
    tray = win_tray.WindowsTray()
    tray.run(on_quit=lambda: None)
    tray._icon = Icon.last
    items = list(Icon.last.menu.items)
    toggle = next(i for i in items if i._text == "Camera")
    line = items[items.index(toggle) + 1]

    tray.set_state(TrayModel())  # an older daemon / no camera feature: nothing to show
    assert toggle.visible is False and line.visible is False

    tray.set_state(TrayModel(camera=_status(holders=("gaze",))["camera"]))
    assert toggle.visible and toggle.checked is True
    assert line.text == "Camera held by: gaze"
    before = Icon.last.updates
    tray.set_state(TrayModel(camera=_status(state="off")["camera"]))
    assert toggle.checked is False and "released" in line.text
    assert Icon.last.updates == before + 1  # the menu is rebuilt when the camera changes
