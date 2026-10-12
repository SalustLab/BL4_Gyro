"""Native Gyro Aim for Borderlands 4.

The controller's real gyro (read by bl4gyro.dll through the game's own Steam Input) is added to BL4's camera with
the same calls the game uses for look input (AddYawInput / AddPitchInput), once per camera update on the game
thread. No mouse or stick emulation, so the right stick keeps working and the UI never switches to KBM prompts.
Measured on Steam build 25372571: see evidence/PHASE-B.md in the project repository.
"""

import ctypes
import re
import time
from pathlib import Path

import unrealsdk
from mods_base import BoolOption, ButtonOption, SliderOption, SpinnerOption, build_mod, get_pc
from unrealsdk import logging
from unrealsdk.hooks import Type, add_hook, remove_hook

__version__ = "0.1.0"
__version_info__ = (0, 1, 0)
__author__ = "bl4-native-gyro"

HERE = Path(__file__).parent
FRAME_HOOK = "/Script/Engine.CameraModifier:BlueprintModifyCamera"  # game thread, every camera update, also when paused
HOOK_ID = "native_gyro_frame"
# shortcut: BL4's legacy input scales, measured on build 25372571 (AddYawInput(10) -> +25 deg, AddPitchInput(5) -> -12.5 deg);
# re-measure with the probe if a patch changes them.
YAW_SCALE, PITCH_SCALE = 2.5, -2.5
ADS_STATES = (1, 2)  # EZoomState.ZoomingIn, EZoomState.Zoomed
TESTED_BUILD = "25372571"
SAME_UPDATE_S = 0.001  # the hook fires once per camera modifier; one pass per camera update is enough

_dll: ctypes.CDLL | None = None
_state = {"last": 0.0, "errors": 0, "statics": None, "character": None}


def _set(key: str, value: float) -> None:
    if _dll is not None:
        _dll.bl4gyro_set(key.encode(), float(value))


def _setter(key: str, convert=float):
    return lambda _option, value: _set(key, convert(value))


sens_x = SliderOption("Horizontal sensitivity", 2.0, 0.1, 10.0, 0.1, False,
                      description="Camera degrees per degree the controller turns left/right. Starting value, tune to taste.",
                      on_change_anytime=_setter("sens_x"))
sens_y = SliderOption("Vertical sensitivity", 2.0, 0.1, 10.0, 0.1, False,
                      description="Camera degrees per degree the controller tilts up/down.",
                      on_change_anytime=_setter("sens_y"))
ads_multiplier = SliderOption("ADS sensitivity multiplier", 1.0, 0.1, 2.0, 0.05, False,
                              description="Multiplies both sensitivities while aiming down sights.",
                              on_change_anytime=_setter("ads_multiplier"))
invert_x = BoolOption("Invert horizontal", False, on_change_anytime=_setter("invert_x", int))
invert_y = BoolOption("Invert vertical", False, on_change_anytime=_setter("invert_y", int))
space = SpinnerOption("Gyro space", "Player", ["Player", "Local"],
                      description="Player: turning works however you hold the controller (recommended). "
                                  "Local: only the controller's own yaw axis.",
                      on_change_anytime=lambda _o, v: _set("player_space", v == "Player"))
auto_calibrate = BoolOption("Automatic calibration", True,
                            description="Continuously removes gyro drift whenever the controller is still.",
                            on_change_anytime=_setter("auto_calibrate", int))
tighten = SliderOption("Tightening (deg/s)", 0.0, 0.0, 10.0, 0.5, False,
                       description="Slows only very small motions below this speed. 0 = off.",
                       on_change_anytime=_setter("tighten_dps"))
smoothing = SliderOption("Smoothing threshold (deg/s)", 0.0, 0.0, 10.0, 0.5, False,
                         description="Smooths only motions below this speed; faster motion stays raw. 0 = off.",
                         on_change_anytime=_setter("smooth_dps"))


@ButtonOption("Calibrate now", description="Put the controller down on a still surface, then press. Takes 3 seconds.")
def calibrate_now(_button) -> None:
    if _dll is not None:
        _dll.bl4gyro_calibrate(3.0)
        logging.info("[NativeGyro] calibrating for 3 s - keep the controller still")


@ButtonOption("Show status")
def show_status(_button) -> None:
    logging.info(f"[NativeGyro] {_status()}")


def _status() -> str:
    if _dll is None:
        return "not running"
    buf = ctypes.create_string_buffer(256)
    _dll.bl4gyro_status(buf, len(buf))
    return buf.value.decode(errors="replace")


def _push_settings() -> None:
    _set("sens_x", sens_x.value)
    _set("sens_y", sens_y.value)
    _set("ads_multiplier", ads_multiplier.value)
    _set("invert_x", invert_x.value)
    _set("invert_y", invert_y.value)
    _set("player_space", space.value == "Player")
    _set("auto_calibrate", auto_calibrate.value)
    _set("tighten_dps", tighten.value)
    _set("smooth_dps", smoothing.value)


def _load_dll() -> ctypes.CDLL:
    dll = ctypes.CDLL(str(HERE / "bl4gyro.dll"))
    dll.bl4gyro_start.argtypes = [ctypes.c_wchar_p, ctypes.c_char_p]
    dll.bl4gyro_start.restype = ctypes.c_int
    dll.bl4gyro_set.argtypes = [ctypes.c_char_p, ctypes.c_double]
    dll.bl4gyro_set.restype = ctypes.c_int
    dll.bl4gyro_calibrate.argtypes = [ctypes.c_double]
    dll.bl4gyro_take.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)]
    dll.bl4gyro_status.argtypes = [ctypes.c_char_p, ctypes.c_int]
    dll.bl4gyro_status.restype = ctypes.c_int
    return dll


def _installed_build() -> str:
    # <library>/steamapps/common/Borderlands 4/sdk_mods/NativeGyro -> <library>/steamapps/appmanifest_1285190.acf
    manifest = HERE.parents[3] / "appmanifest_1285190.acf"
    try:
        match = re.search(r'"buildid"\s+"(\d+)"', manifest.read_text(errors="replace"))
        return match.group(1) if match else "unknown"
    except OSError:
        return "unknown"


_YAW = ctypes.c_double()
_PITCH = ctypes.c_double()


def _on_camera_update(_obj, _args, _ret, _func) -> None:
    now = time.perf_counter()
    if now - _state["last"] < SAME_UPDATE_S:
        return
    _state["last"] = now
    try:
        pc = get_pc(possibly_loading=True)
        pawn = pc.Pawn if pc is not None else None
        on_foot = pawn is not None and pawn.Class._inherits(_state["character"])  # vehicles: untested, gyro off
        ads = on_foot and int(pawn.ZoomState.State) in ADS_STATES
        # Always drain, so motion made while the gate is closed (menus, pause, vehicles) never jumps in later.
        _dll.bl4gyro_take(int(ads), ctypes.byref(_YAW), ctypes.byref(_PITCH))
        if not on_foot or pc.bShowMouseCursor or pc.IsLookInputIgnored():
            return
        if _state["statics"].IsGamePaused(pc) or pc.GetViewTarget() != pawn:
            return
        if _YAW.value:
            pc.AddYawInput(_YAW.value / YAW_SCALE)
        if _PITCH.value:
            pc.AddPitchInput(_PITCH.value / PITCH_SCALE)
        _state["errors"] = 0
    except Exception as e:  # noqa: BLE001 - never let a per-frame error escape into the game
        _state["errors"] += 1
        if _state["errors"] <= 3:
            logging.error(f"[NativeGyro] camera update failed: {type(e).__name__}: {e}")
        if _state["errors"] == 100:
            remove_hook(FRAME_HOOK, Type.PRE, HOOK_ID)
            logging.error("[NativeGyro] disabled camera injection after repeated errors (game update?)")


def on_enable() -> None:
    global _dll
    if _dll is None:
        _dll = _load_dll()
    replay = (HERE / "replay.csv") if (HERE / "replay.csv").is_file() else None  # dev: repeatable in-game tests
    _push_settings()
    _dll.bl4gyro_start(str(HERE / "bl4gyro.log"), str(replay).encode() if replay else None)
    _state.update(last=0.0, errors=0, statics=unrealsdk.find_class("GameplayStatics").ClassDefaultObject,
                  character=unrealsdk.find_class("OakCharacter"))
    add_hook(FRAME_HOOK, Type.PRE, HOOK_ID, _on_camera_update)
    build = _installed_build()
    if build != TESTED_BUILD:
        logging.warning(f"[NativeGyro] game build {build} differs from the tested build {TESTED_BUILD}; "
                        "if aiming misbehaves, disable the mod and report it")
    logging.info(f"[NativeGyro] enabled (game build {build}{', REPLAY' if replay else ''})")


def on_disable() -> None:
    remove_hook(FRAME_HOOK, Type.PRE, HOOK_ID)
    if _dll is not None:
        _dll.bl4gyro_stop()
    logging.info("[NativeGyro] disabled")


build_mod(name="Native Gyro Aim", description="Real controller gyro added to BL4's native camera (Steam Input motion, Switch Pro / DualSense / DS4).")
