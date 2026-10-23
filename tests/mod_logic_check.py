"""Checks the mod's game-independent logic (mod/BL4Gyro/state.py) outside the game.
usage: python -I tests/mod_logic_check.py
"""
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("state", Path(__file__).parents[1] / "mod" / "BL4Gyro" / "state.py")
state = importlib.util.module_from_spec(spec)
sys.modules["state"] = state  # dataclasses resolve annotations through sys.modules
spec.loader.exec_module(state)

failures = 0


def check(ok: bool, what: str) -> None:
    global failures
    if not ok:
        failures += 1
        print(f"FAIL: {what}")


def inject(**over) -> bool:
    args = dict(gyro_enabled=True, panel_open=False, calibrating=False, mode="Always", button_held=False, ads=False,
                gate_open=True)
    args.update(over)
    return state.should_inject(**args)


def precedence() -> None:
    check(inject(), "always on, gate open -> inject")
    for blocker in ("gyro_enabled", "gate_open"):
        check(not inject(**{blocker: False}), f"{blocker}=False blocks")
    for blocker in ("panel_open", "calibrating"):
        for mode in state.MODES:
            check(not inject(**{blocker: True}, mode=mode, button_held=True, ads=True), f"{blocker} blocks in {mode}")
    check(not inject(button_held=True), "gyro button suspends in Always")
    check(not inject(mode="ADS only"), "ADS only, hip fire -> off")
    check(inject(mode="ADS only", ads=True), "ADS only, aiming -> on")
    check(not inject(mode="ADS only", ads=True, button_held=True), "gyro button suspends in ADS only")
    check(not inject(mode="Hold button"), "Hold mode, button up -> off")
    check(inject(mode="Hold button", button_held=True), "Hold mode, button down -> on")
    check(not inject(mode="Hold button", button_held=True, gate_open=False), "game gate still wins in Hold mode")


def combo() -> None:
    c = state.Combo(("L3", "R3"))
    check(not c.press("L3", 0.0), "first key passes to the game")
    check(c.press("R3", 0.1), "second key is blocked")
    check(not c.poll(0.5), "not before the hold time")
    check(c.poll(0.61), "fires after the hold time")
    check(not c.poll(2.0), "fires once per hold")
    c.release("R3")
    check(not c.poll(3.0), "partial release stops it")
    check(c.press("R3", 3.0) and not c.poll(3.6), "re-press while the other is still held does not re-fire")
    c.release("R3")
    c.release("L3")
    c.press("R3", 5.0)
    c.press("L3", 5.1)
    check(c.poll(5.7), "fires again after a full release, either order")
    single = state.Combo(("F8",))
    check(not single.press("F8", 0.0), "one-key combo is not blocked")


def repeater() -> None:
    r = state.Repeater()
    r.press("up", 0.0)
    check(r.poll(0.2) is None, "no repeat before the delay")
    check(r.poll(0.41) == "up" and r.poll(0.45) is None and r.poll(0.5) == "up", "repeats at the rate")
    r.release("up")
    check(r.poll(1.0) is None, "stops on release")


def numbers() -> None:
    check(state.parse_number("2,5") == 2.5 and state.parse_number(" 3 ") == 3.0, "comma and dot")
    check(state.parse_number("abc") is None and state.parse_number("nan") is None and state.parse_number("") is None,
          "garbage rejected")
    check(state.snap(3.04, 0.1, 10.0, 0.01) == 3.04, "fine grid kept")
    check(state.snap(2.0 + 0.1 * 3, 0.1, 10.0, 0.1) == 2.3, "no float noise")
    check(state.snap(99, 0.1, 10.0, 0.1) == 10.0 and state.snap(-5, 0.1, 10.0, 0.1) == 0.1, "clamped")


def settings() -> None:
    check(state.first_run(None) and state.first_run({}) and state.first_run({"options": {}}), "no 'enabled' = first run")
    check(not state.first_run({"enabled": False}), "saved 'disabled' is kept")
    check(state.sanitize("x", 2.0, 0.1, 10.0) == 2.0 and state.sanitize(50, 2.0, 0.1, 10.0) == 10.0, "slider recovery")
    check(state.sanitize(float("inf"), 2.0, 0.1, 10.0) == 2.0 and state.sanitize(True, 2.0, 0.1, 10.0) == 2.0,
          "inf/bool are not numbers")
    check(state.sanitize(1, False) is False and state.sanitize(True, False) is True, "bools stay bools")
    check(state.sanitize("Sideways", "Player", choices=("Player", "Local")) == "Player", "unknown choice -> default")
    v01 = {"Horizontal sensitivity": 3.0, "Vertical sensitivity": 3.0}
    check(state.link_vertical_default(v01) is True, "0.1 file with equal axes -> linked")
    check(state.link_vertical_default({"Horizontal sensitivity": 3.0, "Vertical sensitivity": 2.0}) is False,
          "0.1 file with different axes -> unlinked (feel unchanged)")
    check(state.link_vertical_default({**v01, "Link vertical": False}) is None, "existing choice kept")
    check(state.link_vertical_default({}) is None, "fresh install -> option default")


def menu() -> None:
    values = {"on": True, "sens": 2.0, "mode": "Always", "reset": 0}
    m = state.Menu({
        "Main": [
            state.Row("Gyro", "toggle", lambda: values["on"], lambda v: values.update(on=v)),
            state.Row("Status", "info", lambda: "ok"),
            state.Row("Sensitivity", "slider", lambda: values["sens"], lambda v: values.update(sens=v),
                      lo=0.1, hi=10.0, step=0.1, fine=0.01),
            state.Row("Mode", "choice", lambda: values["mode"], lambda v: values.update(mode=v), choices=state.MODES),
            state.Row("Advanced", "section", target="Advanced"),
        ],
        "Advanced": [
            state.Row("Restore defaults", "action", set=lambda _v: values.update(reset=values["reset"] + 1),
                      confirm="Restore all settings to defaults?"),
        ],
    })
    m.confirm()
    check(values["on"] is False, "A toggles")
    m.move(1)
    check(m.focused().label == "Sensitivity", "info rows are skipped")
    m.adjust(1)
    m.adjust(1, fine=True)
    check(values["sens"] == 2.11, f"step + fine step ({values['sens']})")
    m.confirm()
    check(m.entry is None and values["sens"] == 2.11, "A on a slider does nothing (controller only)")
    for ch in "3,5":
        m.type_char(ch)
    m.confirm()
    check(values["sens"] == 3.5 and m.entry is None, "typed digits + Enter, with comma")
    for ch in "42":
        m.type_char(ch)
    m.confirm()
    check(values["sens"] == 10.0 and "Limited" in m.message, "entry is clamped and explained")
    m.type_char("7")
    m.back()
    check(values["sens"] == 10.0 and m.entry is None, "B cancels typing")
    m.move(1)
    m.adjust(-1)
    check(values["mode"] == "Hold button", "choice wraps")
    m.move(1)
    m.confirm()
    check(m.section == "Advanced", "section opens")
    m.confirm()
    check(values["reset"] == 0 and m.asking is not None, "action asks first")
    check(not m.back() and values["reset"] == 0, "B declines")
    m.confirm()
    m.confirm()
    check(values["reset"] == 1, "A confirms")
    check(not m.back() and m.section == "Main" and m.focused().label == "Advanced", "B returns to the same row")
    check(m.back(), "B on Main closes")
    m.move(-1)
    check(m.focused().label == "Mode", "position is kept between openings")


def button_labels() -> None:
    ps_names = ["X", "O", "L1", "R1"]
    check(state.pad_labels("Nintendo", ps_names, "PS5") == ("B", "A", "L", "R"), "Nintendo wins over detected names")
    check(state.pad_labels("Xbox", ps_names, "PS5") == ("A", "B", "LB", "RB"), "Xbox wins over detected names")
    check(state.pad_labels("PlayStation", None, "xbox360") == ("X", "O", "L1", "R1"), "PlayStation without names")
    check(state.pad_labels("Auto", ps_names, "xbox360") == ("X", "O", "L1", "R1"), "Auto uses the detected names")
    check(state.pad_labels("Auto", None, "PS5") == ("X", "O", "L1", "R1"), "Auto fallback: PlayStation family")
    check(state.pad_labels("Auto", None, "SwitchProController") == ("B", "A", "L", "R"), "Auto fallback: Switch")
    check(state.pad_labels("Auto", None, "unknown") == ("A", "B", "LB", "RB"), "Auto fallback: Xbox")
    check(state.sanitize("Sega", "Auto", choices=state.BUTTON_NAMES) == "Auto", "bad saved value -> Auto")


def calibration_label() -> None:
    zero, learned = (0.0, 0.0, 0.0), (0.013, 0.020, 0.017)
    label = state.calibration_label
    check(label(2, 1.0, learned, True) == "Calibrated", "manual calibration wins")
    check(label(0, 0.0, learned, True) == "Auto-calibrated", "new session: automatic offset learned")
    check(label(0, 0.0, learned, False) == "Auto-calibrated", "learned offset kept after auto is turned off")
    check(label(0, 0.0, zero, True).startswith("Calibrating automatically"), "auto on, nothing learned yet")
    check(label(0, 0.0, zero, False) == "Not calibrated yet", "auto off, never calibrated")
    check(label(1, 0.5, zero, True) == "Measuring 50% - don't touch it", "manual progress")
    check(label(3, 0.0, learned, True).startswith("It moved"), "rejected manual calibration still says so")


for test in (precedence, combo, repeater, numbers, settings, menu, button_labels, calibration_label):
    test()
print("OK" if not failures else f"{failures} FAILED")
sys.exit(1 if failures else 0)
