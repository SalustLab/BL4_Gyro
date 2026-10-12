"""Phase B probe (dev only, not distributed): answers "how do we rotate BL4's camera natively".

Keys (in gameplay):
  F7  toggle unrealsdk call logging (unrealsdk.calls.tsv next to the game exe) - finds per-frame UFunctions
  F8  snapshot: camera/controller state, gate flags, FOV, input scales, motion-control settings
  F9  AddYawInput(10) + AddPitchInput(5) once      -> compare ControlRotation with the next F8
  F10 SetControlRotation(yaw + 10)                  -> compare with the next F8
  F11 RotationInput.Yaw += 10 (raw member write)    -> compare with the next F8
Everything is appended to probe.log in this folder and echoed to the console.
"""

import time
from pathlib import Path

import unrealsdk
from mods_base import build_mod, get_pc, keybind
from unrealsdk import logging
from unrealsdk.hooks import log_all_calls

LOG = Path(__file__).with_name("probe.log")
_logging_calls = False


def out(msg: str) -> None:
    logging.info(f"[probe] {msg}")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


def safe(fn):  # every probe read is best effort: report the error instead of breaking the mod
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return f"<{type(e).__name__}: {e}>"


def rot(r) -> str:
    return f"(P {r.Pitch:+.4f} Y {r.Yaw:+.4f} R {r.Roll:+.4f})"


def name(obj) -> str:
    return "None" if obj is None else f"{obj.Class.Name}:{obj.Name}"


@keybind("Probe: toggle call logging", "F7")
def toggle_calls() -> None:
    global _logging_calls
    _logging_calls = not _logging_calls
    log_all_calls(_logging_calls)
    out(f"log_all_calls = {_logging_calls}")


@keybind("Probe: snapshot", "F8")
def snapshot() -> None:
    pc = get_pc()
    cam = safe(lambda: pc.PlayerCameraManager)
    lp = safe(lambda: pc.Player)
    out("--- snapshot")
    out(f"pc {name(pc)}  pawn {safe(lambda: name(pc.Pawn))}  viewtarget {safe(lambda: name(pc.GetViewTarget()))}")
    out(f"ControlRotation {safe(lambda: rot(pc.ControlRotation))}  RotationInput {safe(lambda: rot(pc.RotationInput))}")
    out(
        f"gate: bShowMouseCursor {safe(lambda: pc.bShowMouseCursor)}  IsPaused {safe(lambda: pc.IsPaused())}  "
        f"IsLookInputIgnored {safe(lambda: pc.IsLookInputIgnored())}  IsMoveInputIgnored {safe(lambda: pc.IsMoveInputIgnored())}"
    )
    out(f"camera {safe(lambda: name(cam))}  FOV {safe(lambda: cam.GetFOVAngle())}  DefaultFOV {safe(lambda: cam.DefaultFOV)}")
    out(
        f"input scales: InputYawScale_DEPRECATED {safe(lambda: pc.InputYawScale_DEPRECATED)}  "
        f"InputPitchScale_DEPRECATED {safe(lambda: pc.InputPitchScale_DEPRECATED)}  "
        f"bEnableLegacyInputScales {safe(lambda: unrealsdk.find_class('InputSettings').ClassDefaultObject.bEnableLegacyInputScales)}"
    )
    out(
        f"local player {safe(lambda: name(lp))}  MotionControls {safe(lambda: lp.GetMotionControlsSetting())}  "
        f"MotionLook H/V {safe(lambda: lp.HorizontalMotionControlsLookSensitivity)}/{safe(lambda: lp.VerticalMotionControlsLookSensitivity)}"
    )


@keybind("Probe: AddYawInput(10) + AddPitchInput(5)", "F9")
def add_input() -> None:
    pc = get_pc()
    before = rot(pc.ControlRotation)
    pc.AddYawInput(10.0)
    pc.AddPitchInput(5.0)
    out(f"F9 AddYawInput(10)+AddPitchInput(5) called; ControlRotation before {before}; RotationInput now {rot(pc.RotationInput)}")


@keybind("Probe: SetControlRotation(yaw + 10)", "F10")
def set_control_rotation() -> None:
    pc = get_pc()
    r = pc.ControlRotation
    before = rot(r)
    pc.SetControlRotation(unrealsdk.make_struct("Rotator", Pitch=r.Pitch, Yaw=r.Yaw + 10.0, Roll=r.Roll))
    out(f"F10 SetControlRotation(yaw+10); before {before}; right after {rot(pc.ControlRotation)}")


@keybind("Probe: RotationInput.Yaw += 10", "F11")
def write_rotation_input() -> None:
    pc = get_pc()
    before = rot(pc.ControlRotation)
    pc.RotationInput.Yaw = pc.RotationInput.Yaw + 10.0
    out(f"F11 RotationInput.Yaw += 10; ControlRotation before {before}; RotationInput now {rot(pc.RotationInput)}")


def _startup_report() -> None:
    out("=== probe loaded")
    out(f"ctypes: {safe(lambda: __import__('ctypes').__name__ + ' OK')}")


mod = build_mod()
_startup_report()
mod.enable()  # dev probe: no need to enable it through the menu
