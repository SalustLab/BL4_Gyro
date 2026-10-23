"""Borderlands 4 Gyro (BL4 Gyro).

The controller's real gyro (read by bl4gyro.dll through the game's own Steam Input) is added to BL4's camera with
the same calls the game uses for look input (AddYawInput / AddPitchInput), once per camera update on the game
thread. No mouse or stick emulation, so the right stick keeps working and the UI never switches to KBM prompts.
Measured on Steam build 25372571.

Everything is set from the in-game panel (default: hold L3 + R3, or F8); the console mod menu still works.
"""

import ctypes
import json
import re
import time
from pathlib import Path

import unrealsdk
from mods_base import (SETTINGS_DIR, BoolOption, ButtonOption, HiddenOption, SliderOption, SpinnerOption, build_mod,
                       get_pc, keybind)
from unrealsdk import logging
from unrealsdk.hooks import Type, add_hook, remove_hook

from . import panel, state

__version__ = "1.0.0"
__version_info__ = (0, 2, 0)
__author__ = "bl4-gyro"

HERE = Path(__file__).parent
SETTINGS_FILE = SETTINGS_DIR / "BL4Gyro.json"
FRAME_HOOK = "/Script/Engine.CameraModifier:BlueprintModifyCamera"  # game thread, every camera update, also when paused
HOOK_ID = "bl4_gyro_frame"
# shortcut: BL4's legacy input scales, measured on build 25372571 (AddYawInput(10) -> +25 deg, AddPitchInput(5) -> -12.5 deg);
# re-measure (one AddYawInput/AddPitchInput call, read ControlRotation) if a patch changes them.
YAW_SCALE, PITCH_SCALE = 2.5, -2.5
ADS_STATES = (1, 2)  # EZoomState.ZoomingIn, EZoomState.Zoomed
TESTED_BUILD = "25372571"
SAME_UPDATE_S = 0.001  # the hook fires once per camera modifier; one pass per camera update is enough
CALIBRATION_S, CALIBRATION_COUNTDOWN_S = 4.0, 5.0  # time to hold the controller still, then measuring
SAVE_DELAY_S = 1.0
MAX_ERRORS = 100
SOURCES = ("No controller", "Steam Input", "HID (SDL)", "Replay", "Steam Input unavailable")

_dll: ctypes.CDLL | None = None
_state = {"last": 0.0, "errors": 0, "statics": None, "character": None, "gate_open": False, "stopped": False,
          "dirty_at": None, "cal_start_at": None, "started_at": 0.0, "seen": None}
_syncing = False


def _set(key: str, value: float) -> None:
    if _dll is not None:
        _dll.bl4gyro_set(key.encode(), float(value))


def _changed() -> None:
    _state["dirty_at"] = time.perf_counter()  # saved SAVE_DELAY_S after the last change, never per frame


def _setter(key: str, convert=float):
    def apply(_option, value) -> None:
        _set(key, convert(value))
        _changed()
    return apply


def _apply_sens(x: float | None = None, y: float | None = None, link: bool | None = None) -> None:
    """While linked, changing either sensitivity changes the other; turning the link on copies horizontal to
    vertical. Callbacks run before the option stores its new value, so it comes in as an argument."""
    global _syncing
    x = sens_x.value if x is None else x
    y = sens_y.value if y is None else y
    link = link_vertical.value if link is None else link
    if link and not _syncing:
        _syncing = True
        try:
            if y != sens_y.value:  # vertical was changed: horizontal follows
                x = y
                sens_x.value = x
            else:                  # horizontal changed, or the link was turned on: vertical follows
                y = x
                sens_y.value = y
        finally:
            _syncing = False
    _set("sens_x", x)
    _set("sens_y", y)
    _changed()


gyro_enabled = BoolOption("Gyro enabled", True,
                          description="Turns gyro aiming on or off. The panel stays available either way.",
                          on_change_anytime=lambda _o, _v: _changed())
mode = SpinnerOption("Activation mode", "Always", list(state.MODES),
                     description="Always: gyro whenever you play. ADS only: only while aiming down sights. "
                                 "Hold button: only while the gyro button is held.",
                     on_change_anytime=lambda _o, _v: _changed())
# Identifiers are the keys saved by 0.1; only the display names changed.
sens_x = SliderOption("Horizontal sensitivity", 2.0, 0.1, 10.0, 0.1, False,
                      description="Camera degrees per degree you turn the controller left/right.",
                      on_change_anytime=lambda _o, v: _apply_sens(x=v))
ads_multiplier = SliderOption("ADS sensitivity multiplier", 0.75, 0.1, 2.0, 0.05, False,
                              description="Multiplies the sensitivity while aiming down sights. Below 1 = steadier aim.",
                              on_change_anytime=_setter("ads_multiplier"))
link_vertical = BoolOption("Link vertical", False, display_name="Grouped sensitivity",
                           description="On: one sensitivity for both directions. Off: horizontal and vertical "
                                       "separately.",
                           on_change_anytime=lambda _o, v: _apply_sens(link=v))
sens_y = SliderOption("Vertical sensitivity", 1.2, 0.1, 10.0, 0.1, False,
                      description="Camera degrees per degree you tilt the controller up/down.",
                      on_change_anytime=lambda _o, v: _apply_sens(y=v))
invert_x = BoolOption("Invert horizontal", False, on_change_anytime=_setter("invert_x", int))
invert_y = BoolOption("Invert vertical", False, on_change_anytime=_setter("invert_y", int))
space = SpinnerOption("Gyro space", "Player", ["Player", "Local"],
                      description="Player: turning works however you hold the controller (recommended). "
                                  "Local: only the controller's own yaw axis.",
                      on_change_anytime=lambda _o, v: (_set("player_space", v == "Player"), _changed()))
auto_calibrate = BoolOption("Automatic calibration", True,
                            description="While a menu, the map or the pause screen is open, removes gyro drift whenever "
                                        "the controller lies still (e.g. on the desk). Never runs while you aim.",
                            on_change_anytime=lambda _o, v: (_apply_auto_calibration(v), _changed()))
tighten = SliderOption("Tightening (deg/s)", 0.0, 0.0, 10.0, 0.5, False,
                       description="Slows only very small motions below this speed (steadier, less precise). 0 = off.",
                       on_change_anytime=_setter("tighten_dps"))
smoothing = SliderOption("Smoothing threshold (deg/s)", 0.0, 0.0, 10.0, 0.5, False,
                         description="Smooths only motions below this speed; faster motion stays raw. Adds a little "
                                     "delay to slow motion. 0 = off.",
                         on_change_anytime=_setter("smooth_dps"))
combo = SpinnerOption("Panel combo", "L3 + R3", list(panel.COMBOS),
                      description="Hold these controller buttons for half a second during gameplay to open the "
                                  "gyro panel.",
                      on_change_anytime=lambda _o, v: (panel.set_combo(v), _changed()))
debug_trace = BoolOption("Debug trace", False,
                         description="Writes trace.csv in the mod folder (motion packets, camera deltas, ControlRotation "
                                     "per frame) for diagnosis. Leave off for play.",
                         on_change_anytime=_setter("trace", int))
gyro_button = SpinnerOption("Gyro button", "None", list(panel.GYRO_BUTTONS),
                            description="Hold mode: gyro works while held. Always / ADS only: gyro pauses while held, "
                                        "so you can re-center the controller. The button keeps its game action.",
                            on_change_anytime=lambda _o, _v: _changed())
# Not named button_names: that is the DLL wrapper below.
button_labels = SpinnerOption("Button names", "Auto", list(state.BUTTON_NAMES),
                              description="Names used in the panel's button hints. Auto follows your controller; pick "
                                          "one if they look wrong (a Switch 2 pad through Switch2Connect shows up as a "
                                          "DualSense).",
                              on_change_anytime=lambda _o, _v: _changed())
ui = HiddenOption("ui", {"intro_seen": False})

SLIDERS = (sens_x, sens_y, ads_multiplier, tighten, smoothing)
BOOLS = (gyro_enabled, link_vertical, invert_x, invert_y, auto_calibrate, debug_trace)
SPINNERS = (mode, space, combo, gyro_button, button_labels)


@keybind("Open gyro panel", "F8", description="Keyboard alternative to the controller combo.")
def open_panel_key() -> None:
    panel.toggle()


@keybind("Calibrate gyro", None, description="Starts a calibration (put the controller down first).")
def calibrate_key() -> None:
    start_calibration()


@ButtonOption("Calibrate now", description="Hold the controller still (or rest it on a table) within 5 seconds; it measures for 4.")
def calibrate_now(_button) -> None:
    start_calibration()


@ButtonOption("Open gyro panel")
def open_panel_button(_button) -> None:
    panel.open()


def start_calibration() -> None:
    """Countdown first, so the button press and putting the controller down are not measured."""
    if _dll is not None and _state["cal_start_at"] is None:
        _state["cal_start_at"] = time.perf_counter() + CALIBRATION_COUNTDOWN_S


def status() -> str:
    if _dll is None:
        return "not running"
    buf = ctypes.create_string_buffer(256)
    _dll.bl4gyro_status(buf, len(buf))
    return buf.value.decode(errors="replace")


def info() -> dict:
    """bl4gyro_info as names (see core/bl4gyro.cpp)."""
    values = (ctypes.c_double * 8)()
    if _dll is None or _dll.bl4gyro_info(values, 8) < 8:
        return {"source": 0, "packets": 0.0, "since_packet": -1.0, "cal_progress": 0.0, "cal": 0,
                "offset": (0.0, 0.0, 0.0)}
    return {"source": int(values[0]), "packets": values[1], "since_packet": values[2], "cal_progress": values[3],
            "cal": int(values[4]), "offset": tuple(values[5:8])}


def button_names() -> list[str] | None:
    """Printed names of the confirm / back / left / right shoulder buttons of the connected pad, or None."""
    buf = ctypes.create_string_buffer(64)
    if _dll is None or not _dll.bl4gyro_button_names(buf, len(buf)):
        return None
    names = buf.value.decode(errors="replace").split("|")
    return names if len(names) == 4 else None


def buttons() -> int:
    """Controller buttons as bits (panel.PAD_BITS); 0 while the game is not focused."""
    return int(_dll.bl4gyro_buttons()) if _dll is not None else 0


def calibration_text() -> str:
    """Progress tied to the real operation: countdown in Python, then the DLL's sensor-time progress."""
    start_at = _state["cal_start_at"]
    if start_at is not None:
        return f"Keep it still... {max(0.0, start_at - time.perf_counter()):.0f}"
    i = info()
    return state.calibration_label(i["cal"], i["cal_progress"], i["offset"], auto_calibrate.value)


def calibrating() -> bool:
    return _state["cal_start_at"] is not None or info()["cal"] in (1, 5)


def diagnostics() -> str:
    """Shared by the panel's Diagnostics page and Copy diagnostics. No personal data (paths are relative)."""
    i = info()
    return "\n".join([
        f"Borderlands 4 Gyro {__version__}  game build {_installed_build()} (tested {TESTED_BUILD})",
        f"source: {SOURCES[i['source']] if 0 <= i['source'] < len(SOURCES) else i['source']}  status: {status()}",
        f"packets/s {i['packets']:.0f}  last packet {i['since_packet']:.1f}s ago  calibration: {calibration_text()}  "
        "offset {:+.3f} {:+.3f} {:+.3f}".format(*i["offset"]),
        f"gyro {'on' if gyro_enabled.value else 'off'}  mode {mode.value}  gate {'open' if _state['gate_open'] else 'closed'}"
        f"  camera hook {'stopped after errors' if _state['stopped'] else 'running'}",
        f"sens {sens_x.value}/{sens_y.value}{' linked' if link_vertical.value else ''}  ads x{ads_multiplier.value}  "
        f"invert {invert_x.value}/{invert_y.value}  space {space.value}  auto-cal {auto_calibrate.value}  "
        f"tighten {tighten.value}  smoothing {smoothing.value}",
    ])


def _apply_auto_calibration(enabled: bool) -> None:
    # Stillness calibration during aiming eats slow, steady motion (24 deg pan -> 8.5 deg in tests/core_tests.cpp),
    # so it only runs while the game gate is closed - and not while the panel is open: the controller is in the hand
    # then, and slow hand drift learned as bias became a steady camera drift.
    _set("auto_calibrate", enabled and not _state["gate_open"] and not panel.is_open())


def panel_changed() -> None:
    """The panel opened or closed."""
    _apply_auto_calibration(auto_calibrate.value)


def _push_settings() -> None:
    _apply_sens()
    _set("ads_multiplier", ads_multiplier.value)
    _set("invert_x", invert_x.value)
    _set("invert_y", invert_y.value)
    _set("player_space", space.value == "Player")
    _apply_auto_calibration(auto_calibrate.value)
    _set("tighten_dps", tighten.value)
    _set("smooth_dps", smoothing.value)
    _set("trace", debug_trace.value)


def _load_dll() -> ctypes.CDLL:
    dll = ctypes.CDLL(str(HERE / "bl4gyro.dll"))
    dll.bl4gyro_start.argtypes = [ctypes.c_wchar_p, ctypes.c_char_p]
    dll.bl4gyro_start.restype = ctypes.c_int
    dll.bl4gyro_stop.restype = None
    dll.bl4gyro_set.argtypes = [ctypes.c_char_p, ctypes.c_double]
    dll.bl4gyro_set.restype = ctypes.c_int
    dll.bl4gyro_calibrate.argtypes = [ctypes.c_double]
    dll.bl4gyro_calibrate.restype = None
    dll.bl4gyro_take.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)]
    dll.bl4gyro_take.restype = None
    dll.bl4gyro_status.argtypes = [ctypes.c_char_p, ctypes.c_int]
    dll.bl4gyro_status.restype = ctypes.c_int
    dll.bl4gyro_trace_line.argtypes = [ctypes.c_char_p]
    dll.bl4gyro_trace_line.restype = None
    dll.bl4gyro_info.argtypes = [ctypes.POINTER(ctypes.c_double), ctypes.c_int]
    dll.bl4gyro_info.restype = ctypes.c_int
    dll.bl4gyro_buttons.argtypes = []
    dll.bl4gyro_buttons.restype = ctypes.c_uint
    dll.bl4gyro_button_names.argtypes = [ctypes.c_char_p, ctypes.c_int]
    dll.bl4gyro_button_names.restype = ctypes.c_int
    return dll


def _installed_build() -> str:
    # <library>/steamapps/common/Borderlands 4/sdk_mods/BL4Gyro -> <library>/steamapps/appmanifest_1285190.acf
    manifest = HERE.parents[3] / "appmanifest_1285190.acf"
    try:
        match = re.search(r'"buildid"\s+"(\d+)"', manifest.read_text(errors="replace"))
        return match.group(1) if match else "unknown"
    except OSError:
        return "unknown"


_YAW = ctypes.c_double()
_PITCH = ctypes.c_double()


def _housekeeping(now: float) -> None:
    """Per camera update, independent of the gyro injection: calibration countdown and the delayed save."""
    start_at = _state["cal_start_at"]
    if start_at is not None and now >= start_at:
        _state["cal_start_at"] = None
        _dll.bl4gyro_calibrate(CALIBRATION_S)
    dirty_at = _state["dirty_at"]
    if dirty_at is not None and now - dirty_at >= SAVE_DELAY_S and not panel.is_open():
        _state["dirty_at"] = None
        mod.save_settings()


def _on_camera_update(_obj, _args, _ret, _func) -> None:
    now = time.perf_counter()
    if now - _state["last"] < SAME_UPDATE_S:
        return
    _state["last"] = now
    try:
        _housekeeping(now)
        pc = get_pc(possibly_loading=True)
        pawn = pc.Pawn if pc is not None else None
        view = pc.GetViewTarget() if pawn is not None else None
        if debug_trace.value:
            seen = (pawn.Class.Name if pawn else None, view.Class.Name if view else None)
            if seen != _state["seen"]:
                _state["seen"] = seen
                logging.info(f"[BL4Gyro] pawn={seen[0]} view={seen[1]}")
        # ZoomState exists only on foot; in a vehicle the gyro moves the camera like on foot, without ADS.
        ads = pawn is not None and pawn.Class._inherits(_state["character"]) and int(pawn.ZoomState.State) in ADS_STATES
        # Always drain, so motion made while injection is off (menus, pause, panel, suspend) never jumps in later.
        _dll.bl4gyro_take(int(ads), ctypes.byref(_YAW), ctypes.byref(_PITCH))
        gate_open = (pawn is not None and view == pawn and not pc.bShowMouseCursor and not pc.IsLookInputIgnored()
                     and not _state["statics"].IsGamePaused(pc))
        if gate_open != _state["gate_open"]:
            _state["gate_open"] = gate_open
            _apply_auto_calibration(auto_calibrate.value)
        inject = state.should_inject(gyro_enabled=gyro_enabled.value, panel_open=panel.is_open(),
                                     calibrating=calibrating(), mode=mode.value,
                                     button_held=panel.held(gyro_button.value),
                                     ads=ads, gate_open=gate_open)
        if debug_trace.value and pc is not None:
            r = pc.ControlRotation
            _dll.bl4gyro_trace_line(
                f"{r.Yaw:.5f},{r.Pitch:.5f},{_YAW.value:.5f},{_PITCH.value:.5f},{int(inject)},{int(ads)}".encode())
        _state["errors"] = 0
        if not inject:
            return
        if _YAW.value:
            pc.AddYawInput(_YAW.value / YAW_SCALE)
        if _PITCH.value:
            pc.AddPitchInput(_PITCH.value / PITCH_SCALE)
    except Exception as e:  # noqa: BLE001 - never let a per-frame error escape into the game
        _state["errors"] += 1
        if _state["errors"] <= 3:
            logging.error(f"[BL4Gyro] camera update failed: {type(e).__name__}: {e}")
        if _state["errors"] == MAX_ERRORS:
            remove_hook(FRAME_HOOK, Type.PRE, HOOK_ID)
            _state["stopped"] = True
            logging.error("[BL4Gyro] disabled camera injection after repeated errors (game update?)")


def restart_injection() -> None:
    """Diagnostics: re-adds the camera hook after it stopped itself. Safe: it only removes itself again on errors."""
    _state.update(errors=0, stopped=False, last=0.0)
    add_hook(FRAME_HOOK, Type.PRE, HOOK_ID, _on_camera_update)


def _sanitize_options() -> None:
    """Safe recovery from a hand-edited or corrupt settings file."""
    for option in SLIDERS:
        clean = state.sanitize(option.value, option.default_value, option.min_value, option.max_value)
        if clean != option.value:
            option.value = clean
    for option in BOOLS:
        clean = state.sanitize(option.value, option.default_value)
        if clean != option.value:
            option.value = clean
    for option in SPINNERS:
        clean = state.sanitize(option.value, option.default_value, choices=tuple(option.choices))
        if clean != option.value:
            option.value = clean
    if not isinstance(ui.value, dict):
        ui.value = {"intro_seen": False}


def restore_defaults() -> None:
    for option in (*BOOLS, *SLIDERS, *SPINNERS):  # link first, or the sliders sync to one value
        if option is not debug_trace:
            option.value = option.default_value
    open_panel_key.key = open_panel_key.default_key
    calibrate_key.key = None
    mod.save_settings()


def save_now() -> None:
    _state["dirty_at"] = None
    mod.save_settings()


def on_enable() -> None:
    global _dll
    if _dll is None:
        _dll = _load_dll()
    replay = (HERE / "replay.csv") if (HERE / "replay.csv").is_file() else None  # dev: repeatable in-game tests
    _push_settings()
    _dll.bl4gyro_start(str(HERE / "bl4gyro.log"), str(replay).encode() if replay else None)
    _state.update(last=0.0, errors=0, gate_open=False, stopped=False, cal_start_at=None,
                  started_at=time.perf_counter(), statics=unrealsdk.find_class("GameplayStatics").ClassDefaultObject,
                  character=unrealsdk.find_class("OakCharacter"))
    add_hook(FRAME_HOOK, Type.PRE, HOOK_ID, _on_camera_update)
    panel.start(combo.value)
    build = _installed_build()
    if build != TESTED_BUILD:
        logging.warning(f"[BL4Gyro] game build {build} differs from the tested build {TESTED_BUILD}; "
                        "if aiming misbehaves, disable the mod and report it")
    logging.info(f"[BL4Gyro] enabled (game build {build}{', REPLAY' if replay else ''})")


def on_disable() -> None:
    panel.stop()
    remove_hook(FRAME_HOOK, Type.PRE, HOOK_ID)
    if _dll is not None:
        _dll.bl4gyro_stop()
    logging.info("[BL4Gyro] disabled")


def _read_settings() -> dict | None:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


_saved = _read_settings()  # before build_mod: it may rewrite the file
mod = build_mod(name="Borderlands 4 Gyro",
                description="Real controller gyro added to BL4's native camera. Hold L3 + R3 (or press F8) in game "
                            "to open the gyro panel.")
_sanitize_options()
_link = state.link_vertical_default((_saved or {}).get("options", {}) if isinstance(_saved, dict) else {})
if _link is not None:
    link_vertical.value = _link
if state.first_run(_saved):
    mod.enable()  # first launch after install: on by default; later launches keep the user's choice (mods_base)
