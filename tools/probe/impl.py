"""Phase B experiments. Reloaded in game with Insert.

  F9  test A: AddYawInput(10) + AddPitchInput(5)
  F10 test B: SetControlRotation(yaw + 10, bResetCamera=False)
  F11 test C: control run, no injection (shows how much the camera moved on its own)
Each test reads ControlRotation again 0.5 s later on a timer thread: do not touch mouse/sticks meanwhile.
"""

import threading
import time
from pathlib import Path

import unrealsdk
from mods_base import get_pc
from unrealsdk import logging
from unrealsdk.hooks import log_all_calls

HERE = Path(__file__).parent
LOG = HERE / "probe.log"
KEYWORDS = ("rotation", "look", "aim", "zoom", "ads", "motion", "sensitiv", "pause", "fov", "gyro", "cursor",
            "cinematic", "scope", "sight", "menu", "camera", "control")
_calls = {"on": False}


def out(msg: str) -> None:
    logging.info(f"[probe] {msg}")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


def safe(fn):  # probe reads are best effort: report the error instead of breaking the keybind
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return f"<{type(e).__name__}: {e}>"


def rot(r) -> str:
    return f"(P {r.Pitch:+.4f} Y {r.Yaw:+.4f} R {r.Roll:+.4f})"


def name(obj) -> str:
    return "None" if obj is None else f"{obj.Class.Name}:{obj.Name}"


def wrap(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def toggle_calls() -> None:
    _calls["on"] = not _calls["on"]
    log_all_calls(_calls["on"])
    out(f"log_all_calls = {_calls['on']}")


def snapshot() -> None:
    pc = get_pc()
    cam = safe(lambda: pc.PlayerCameraManager)
    lp = safe(lambda: pc.Player)
    statics = unrealsdk.find_class("GameplayStatics").ClassDefaultObject
    out("--- snapshot")
    out(f"pc {name(pc)}  pawn {safe(lambda: name(pc.Pawn))}  viewtarget {safe(lambda: name(pc.GetViewTarget()))}")
    out(f"ControlRotation {safe(lambda: rot(pc.ControlRotation))}")
    out(
        f"gate: bShowMouseCursor {safe(lambda: pc.bShowMouseCursor)}  IsGamePaused {safe(lambda: statics.IsGamePaused(pc))}  "
        f"IsLookInputIgnored {safe(lambda: pc.IsLookInputIgnored())}  IsMoveInputIgnored {safe(lambda: pc.IsMoveInputIgnored())}"
    )
    out(f"camera {safe(lambda: name(cam))}  FOV {safe(lambda: cam.GetFOVAngle())}")
    out(f"MotionControls {safe(lambda: lp.GetMotionControlsSetting())}")


def _readback(label: str, before: tuple[float, float], delay: float = 0.5) -> None:
    def later() -> None:
        pc = get_pc(possibly_loading=True)
        if pc is None:
            out(f"{label}: no pc at readback")
            return
        r = pc.ControlRotation
        out(f"{label}: after {delay}s dYaw {wrap(r.Yaw - before[1]):+.4f}  dPitch {wrap(r.Pitch - before[0]):+.4f}")

    threading.Timer(delay, later).start()


def _before(pc) -> tuple[float, float]:
    r = pc.ControlRotation
    return (r.Pitch, r.Yaw)


def test_a() -> None:  # F9 now toggles the gate watch (F11 does not reach the game on the user's 67% keyboard)
    test_c()


def add_input_once() -> None:  # former test A: AddYawInput(10)+AddPitchInput(5) -> measured +25 / -12.5
    pc = get_pc()
    before = _before(pc)
    pc.AddYawInput(10.0)
    pc.AddPitchInput(5.0)
    out("A: AddYawInput(10) + AddPitchInput(5) called")
    _readback("A", before)


def test_b() -> None:
    pc = get_pc()
    r = pc.ControlRotation
    before = (r.Pitch, r.Yaw)
    pc.SetControlRotation(unrealsdk.make_struct("Rotator", Pitch=r.Pitch, Yaw=r.Yaw + 10.0, Roll=r.Roll), False)
    out(f"B: SetControlRotation(yaw+10, False); right after {rot(pc.ControlRotation)}")
    _readback("B", before)


WATCH_HOOK_ID = "probe_watch"
_watch = {"on": False, "last": None, "calls": 0, "t0": 0.0}


def _gate_state(pc) -> tuple:
    pawn = pc.Pawn
    statics = unrealsdk.find_class("GameplayStatics").ClassDefaultObject
    return (
        ("cursor", safe(lambda: pc.bShowMouseCursor)),
        ("lookIgnored", safe(lambda: pc.IsLookInputIgnored())),
        ("paused", safe(lambda: statics.IsGamePaused(pc))),
        ("pawn", safe(lambda: pawn.Class.Name if pawn else None)),
        ("viewIsPawn", safe(lambda: pc.GetViewTarget() == pawn)),
        ("fov", safe(lambda: round(pc.PlayerCameraManager.GetFOVAngle(), 1))),
        ("zoom", safe(lambda: str(pawn.ZoomState) if pawn else None)),
    )


def _on_watch(obj, _args, _ret, _func) -> None:
    w = _watch
    w["calls"] += 1
    pc = get_pc(possibly_loading=True)
    if pc is None:
        return
    state = _gate_state(pc)
    if state != w["last"]:
        changed = [f"{k}={v}" for (k, v), old in zip(state, w["last"] or [None] * len(state)) if (k, v) != old]
        out(f"WATCH [{time.perf_counter() - w['t0']:7.2f}s] " + "  ".join(changed))
        w["last"] = state


def test_c() -> None:
    """F11: toggles the gate watch - logs, from the per-frame camera hook, only when a gate flag changes."""
    w = _watch
    w["on"] = not w["on"]
    if w["on"]:
        w.update(last=None, calls=0, t0=time.perf_counter())
        unrealsdk.hooks.add_hook(FRAME_HOOK, unrealsdk.hooks.Type.PRE, WATCH_HOOK_ID, _on_watch)
    else:
        unrealsdk.hooks.remove_hook(FRAME_HOOK, unrealsdk.hooks.Type.PRE, WATCH_HOOK_ID)
    out(f"WATCH {'on' if w['on'] else 'off'} (camera-hook calls so far: {w['calls']})")


FRAME_HOOK = "/Script/Engine.CameraModifier:BlueprintModifyCamera"  # ~2 calls per game frame (call log)
_frame = {"n": 0, "target": 0, "mode": "", "before": (0.0, 0.0), "t0": 0.0, "first_obj": None}


def _on_frame(obj, _args, _ret, _func) -> None:
    f = _frame
    if f["first_obj"] is None:
        f["first_obj"] = obj
    if obj != f["first_obj"]:  # one modifier only, so the count is per camera update
        return
    if f["n"] >= f["target"]:
        unrealsdk.hooks.remove_hook(FRAME_HOOK, unrealsdk.hooks.Type.PRE, "probe_frame")
        pc = get_pc()
        r = pc.ControlRotation
        secs = time.perf_counter() - f["t0"]
        out(f"{f['mode']}: {f['n']} camera updates in {secs:.3f}s ({f['n'] / secs:.1f}/s); "
            f"dYaw {wrap(r.Yaw - f['before'][1]):+.4f} dPitch {wrap(r.Pitch - f['before'][0]):+.4f}")
        return
    pc = get_pc()
    if f["mode"] == "D AddYawInput(1)/update":
        pc.AddYawInput(1.0)
    else:
        r = pc.ControlRotation
        pc.SetControlRotation(unrealsdk.make_struct("Rotator", Pitch=r.Pitch, Yaw=r.Yaw + 1.0, Roll=r.Roll), False)
    f["n"] += 1


def _per_frame(mode: str, updates: int = 60) -> None:
    pc = get_pc()
    _frame.update(n=0, target=updates, mode=mode, before=_before(pc), t0=time.perf_counter(), first_obj=None)
    unrealsdk.hooks.add_hook(FRAME_HOOK, unrealsdk.hooks.Type.PRE, "probe_frame", _on_frame)
    out(f"{mode}: started for {updates} camera updates")


def test_d() -> None:
    _per_frame("D AddYawInput(1)/update")


def test_e() -> None:
    _per_frame("E SetControlRotation(yaw+1)/update")


def _dump_members() -> None:
    """Writes reflected members whose names look camera/input related, per class, to members.txt."""
    pc = get_pc(possibly_loading=True)
    if pc is None:
        return
    targets = {
        "pc": pc,
        "pawn": safe(lambda: pc.Pawn),
        "localplayer": safe(lambda: pc.Player),
        "camera": safe(lambda: pc.PlayerCameraManager),
        "playerinput": safe(lambda: pc.PlayerInput),
    }
    lines = []
    for label, obj in targets.items():
        if obj is None or isinstance(obj, str):
            lines.append(f"## {label}: {obj}")
            continue
        lines.append(f"## {label}: {name(obj)}")
        for struct in obj.Class._superfields():
            for field in struct._fields():
                if any(k in field.Name.lower() for k in KEYWORDS):
                    lines.append(f"  {struct.Name}.{field.Name}  [{field.Class.Name}]")
        for prop in obj.Class._properties():
            if any(k in prop.Name.lower() for k in KEYWORDS):
                lines.append(f"  prop {prop.Name}  [{prop.Class.Name}]  offset {prop.Offset_Internal:#x}")
    (HERE / "members.txt").write_text("\n".join(lines), encoding="utf-8")
    out(f"members.txt written ({len(lines)} lines)")


def _dump_mappings() -> None:
    """B5: every Enhanced Input mapping (context, action, key, modifiers) to mappings.txt; flags motion keys."""
    lines, motion = [], []
    for imc in unrealsdk.find_all("InputMappingContext", exact=False):
        for m in safe(lambda imc=imc: list(imc.Mappings)) or []:
            if isinstance(m, str):
                continue
            key = safe(lambda m=m: str(m.Key.KeyName))
            action = safe(lambda m=m: m.Action.Name if m.Action else None)
            mods = safe(lambda m=m: ",".join(x.Class.Name for x in m.Modifiers if x))
            line = f"{imc.Name}\t{action}\t{key}\t{mods}"
            lines.append(line)
            if any(k in str(key).lower() for k in ("rotationrate", "tilt", "gravity", "acceleration", "gyro", "motion")):
                motion.append(line)
    (HERE / "mappings.txt").write_text("\n".join(sorted(set(lines))), encoding="utf-8")
    out(f"mappings.txt written ({len(lines)} mappings); motion-key mappings: {motion if motion else 'none'}")


SPIKE_HOOK_ID = "probe_spike"
SPIKE_KEYS = ("Gamepad_DPad_Up", "Gamepad_DPad_Down", "Gamepad_DPad_Left", "Gamepad_DPad_Right",
              "Gamepad_FaceButton_Bottom", "Gamepad_FaceButton_Right", "Gamepad_FaceButton_Top",
              "Gamepad_FaceButton_Left", "Gamepad_LeftShoulder", "Gamepad_RightShoulder", "Gamepad_LeftTrigger",
              "Gamepad_RightTrigger", "Gamepad_LeftThumbstick", "Gamepad_RightThumbstick", "Gamepad_Special_Left",
              "Gamepad_Special_Right", "Gamepad_LeftX", "Gamepad_LeftY", "Gamepad_Left2D", "Gamepad_RightX",
              "Gamepad_RightY", "Gamepad_LeftTriggerAxis", "Gamepad_RightTriggerAxis", "Up", "Down", "Enter")
_spike = {"on": False, "widget": None, "texts": [], "handles": [], "events": [], "counts": {}, "frames": 0}


def _make_widget(pc):
    """UMG built by reflection: a UserWidget whose tree is Border > VerticalBox > TextBlock x3."""
    lib = unrealsdk.find_class("WidgetBlueprintLibrary").ClassDefaultObject
    widget = None
    for cls_name in ("UserWidget", "GbxUIUMGTickWidget"):
        widget = safe(lambda cls_name=cls_name: lib.Create(pc, unrealsdk.find_class(cls_name), pc))
        out(f"SPIKE Create({cls_name}) -> {widget if isinstance(widget, str) else name(widget)}")
        if widget is not None and not isinstance(widget, str):
            break
    else:
        return None
    tree = widget.WidgetTree
    out(f"SPIKE WidgetTree {name(tree)}")
    if tree is None:
        tree = unrealsdk.construct_object("WidgetTree", widget)
        widget.WidgetTree = tree
    border = unrealsdk.construct_object("Border", tree)
    box = unrealsdk.construct_object("VerticalBox", tree)
    tree.RootWidget = border
    out(f"SPIKE SetContent {safe(lambda: border.SetContent(box))}")
    out(f"SPIKE SetBrushColor {safe(lambda: border.SetBrushColor(unrealsdk.make_struct('LinearColor', R=0.02, G=0.02, B=0.03, A=0.85)))}")
    out(f"SPIKE SetPadding {safe(lambda: border.SetPadding(unrealsdk.make_struct('Margin', Left=24, Top=16, Right=24, Bottom=16)))}")
    texts = []
    for i, size in enumerate((32, 24, 24)):
        t = unrealsdk.construct_object("TextBlock", tree)
        out(f"SPIKE AddChild[{i}] {safe(lambda t=t: box.AddChildToVerticalBox(t))}")
        out(f"SPIKE SetText[{i}] {safe(lambda t=t, i=i: t.SetText(f'Native Gyro spike line {i}'))}")
        font = safe(lambda t=t: t.Font)
        out(f"SPIKE Font[{i}] {safe(lambda font=font: (font.FontObject, font.Size, font.TypefaceFontName))}")
        if not isinstance(font, str):
            font.Size = size
            out(f"SPIKE SetFont[{i}] {safe(lambda t=t, font=font: t.SetFont(font))}")
        texts.append(t)
    color = unrealsdk.make_struct("SlateColor", SpecifiedColor=unrealsdk.make_struct("LinearColor", R=1, G=0.85, B=0.2, A=1))
    out(f"SPIKE SetColorAndOpacity {safe(lambda: texts[0].SetColorAndOpacity(color))}")
    out(f"SPIKE AddToViewport {safe(lambda: widget.AddToViewport(100))}")
    out(f"SPIKE SetAlignment {safe(lambda: widget.SetAlignmentInViewport(unrealsdk.make_struct('Vector2D', X=0.5, Y=0.5)))}")
    out(f"SPIKE SetPosition {safe(lambda: widget.SetPositionInViewport(unrealsdk.make_struct('Vector2D', X=960, Y=540), True))}")
    out(f"SPIKE SetDesiredSize {safe(lambda: widget.SetDesiredSizeInViewport(unrealsdk.make_struct('Vector2D', X=900, Y=300)))}")
    layout = unrealsdk.find_class("WidgetLayoutLibrary").ClassDefaultObject
    out(f"SPIKE viewport size {safe(lambda: tuple(layout.GetViewportSize(pc)))}  scale {safe(lambda: layout.GetViewportScale(pc))}")
    out(f"SPIKE IsInViewport {safe(lambda: widget.IsInViewport())}")
    _spike["texts"] = texts
    return widget


def _on_key(key: str):
    def cb(event):
        c = _spike["counts"]
        ev = getattr(event, "name", str(event))
        c[(key, ev)] = c.get((key, ev), 0) + 1
        if c[(key, ev)] <= 3:
            _spike["events"].append(f"{key}:{ev}")
        if key != "*" and ev != "IE_Axis":
            _spike["last"] = f"{key} {ev}"
        if not _spike["on"] or ev == "IE_Released":
            return None
        return unrealsdk.hooks.Block
    return cb


def _on_spike_frame(_obj, _args, _ret, _func) -> None:
    s = _spike
    s["frames"] += 1
    if s["frames"] % 2 or not s["texts"]:
        return
    pc = get_pc(possibly_loading=True)
    paused = safe(lambda: unrealsdk.find_class("GameplayStatics").ClassDefaultObject.IsGamePaused(pc))
    safe(lambda: s["texts"][1].SetText(f"frame {s['frames'] // 2}  paused {paused}"))
    safe(lambda: s["texts"][2].SetText(f"last key: {s.get('last', '-')}"))


def ui_spike_v1() -> None:
    """Former F10 (v1): on = panel shown + pad keys blocked (releases pass) + ignore move; off = everything restored."""
    from keybinds.keybinds import deregister_keybind, register_keybind

    s = _spike
    pc = get_pc()
    if not s["on"]:
        s.update(on=True, events=[], counts={}, frames=0, last="-")
        out("SPIKE === on")
        s["widget"] = safe(lambda: _make_widget(pc))
        out(f"SPIKE widget {s['widget'] if isinstance(s['widget'], str) else name(s['widget'])}")
        s["handles"] = [register_keybind(k, None, _on_key(k)) for k in SPIKE_KEYS]
        s["handles"].append(register_keybind(None, None, _on_key("*")))
        out(f"SPIKE SetIgnoreMoveInput {safe(lambda: pc.SetIgnoreMoveInput(True))}  moveIgnored {safe(lambda: pc.IsMoveInputIgnored())}")
        unrealsdk.hooks.add_hook(FRAME_HOOK, unrealsdk.hooks.Type.PRE, SPIKE_HOOK_ID, _on_spike_frame)
        return
    s["on"] = False
    unrealsdk.hooks.remove_hook(FRAME_HOOK, unrealsdk.hooks.Type.PRE, SPIKE_HOOK_ID)
    for h in s["handles"]:
        deregister_keybind(h)
    s["handles"] = []
    out(f"SPIKE ResetIgnoreMoveInput {safe(lambda: pc.ResetIgnoreMoveInput())}  moveIgnored {safe(lambda: pc.IsMoveInputIgnored())}")
    w = s["widget"]
    if w is not None and not isinstance(w, str):
        out(f"SPIKE RemoveFromParent {safe(lambda: w.RemoveFromParent())}")
    s["widget"], s["texts"] = None, []
    out("SPIKE first events (order): " + " ".join(s["events"][:80]))
    out("SPIKE counts: " + "  ".join(f"{k}:{e}={n}" for (k, e), n in sorted(s["counts"].items())))
    out("SPIKE === off")


INPUT_HOOK_ID = "probe_input2"
POLL_KEYS = ("Gamepad_DPad_Up", "Gamepad_DPad_Down", "Gamepad_FaceButton_Bottom", "Gamepad_FaceButton_Right",
             "Gamepad_LeftThumbstick", "Gamepad_RightThumbstick", "Gamepad_LeftShoulder", "Gamepad_RightTrigger",
             "Gamepad_Special_Right", "SpaceBar", "LeftMouseButton")
_spike2 = {"on": False, "down": {}, "removed": [], "subsystem": None}


def _key(name: str):
    return unrealsdk.make_struct("Key", KeyName=name)


def _input_subsystem(pc):
    lib = unrealsdk.find_class("SubsystemBlueprintLibrary").ClassDefaultObject
    return lib.GetLocalPlayerSubSystemFromPlayerController(pc, unrealsdk.find_class("EnhancedInputLocalPlayerSubsystem"))


def _on_poll(_obj, _args, _ret, _func) -> None:
    """Edge-logs key state as the player input sees it (does not depend on the keybinds hook)."""
    s = _spike2
    pc = get_pc(possibly_loading=True)
    if pc is None:
        return
    for k in POLL_KEYS:
        down = safe(lambda k=k: bool(pc.IsInputKeyDown(_key(k))))
        if down != s["down"].get(k):
            if k in s["down"]:
                out(f"SPIKE2 poll {k} -> {down}")
            s["down"][k] = down


def input_spike() -> None:
    """F10 (v2): on = poll pad keys with IsInputKeyDown + remove the player's gameplay mapping contexts;
    off = restore the contexts with their priorities."""
    s = _spike2
    pc = get_pc()
    if not s["on"]:
        s.update(on=True, down={}, removed=[])
        out("SPIKE2 === on")
        sub = safe(lambda: _input_subsystem(pc))
        out(f"SPIKE2 subsystem {sub if isinstance(sub, str) else name(sub)}")
        s["subsystem"] = sub
        statics = unrealsdk.find_class("GameplayStatics").ClassDefaultObject
        out(f"SPIKE3 SetGamePaused(True) -> {safe(lambda: statics.SetGamePaused(pc, True))}  "
            f"IsGamePaused {safe(lambda: statics.IsGamePaused(pc))}")
        if sub is not None and not isinstance(sub, str):
            shown = 0
            for imc in unrealsdk.find_all("InputMappingContext", exact=False):
                found = safe(lambda imc=imc: sub.HasMappingContext(imc))
                if shown < 3 or (not isinstance(found, str) and found and "player" in imc.Name.lower()):
                    shown += 1
                    out(f"SPIKE2 HasMappingContext({imc.Name}) -> {found!r}")
                if isinstance(found, str) or not found:
                    continue
                has, priority = found if isinstance(found, tuple) else (found, 0)
                if not has:
                    continue
                out(f"SPIKE2 applied {imc.Name} priority {priority}")
                if imc.Name.lower().startswith(("context_player", "context_vehicle")):
                    res = safe(lambda imc=imc: sub.RemoveMappingContext(imc, unrealsdk.make_struct("ModifyContextOptions")))
                    out(f"SPIKE2   removed -> {res}")
                    s["removed"].append((imc, priority))
        unrealsdk.hooks.add_hook(FRAME_HOOK, unrealsdk.hooks.Type.PRE, INPUT_HOOK_ID, _on_poll)
        return
    s["on"] = False
    unrealsdk.hooks.remove_hook(FRAME_HOOK, unrealsdk.hooks.Type.PRE, INPUT_HOOK_ID)
    sub = s["subsystem"]
    for imc, priority in s["removed"]:
        opts = unrealsdk.make_struct("ModifyContextOptions", bIgnoreAllPressedKeysUntilRelease=True)
        out(f"SPIKE2 restore {imc.Name} {priority} -> {safe(lambda imc=imc, priority=priority: sub.AddMappingContext(imc, priority, opts))}")
    s["removed"] = []
    statics = unrealsdk.find_class("GameplayStatics").ClassDefaultObject
    out(f"SPIKE3 SetGamePaused(False) -> {safe(lambda: statics.SetGamePaused(pc, False))}  "
        f"IsGamePaused {safe(lambda: statics.IsGamePaused(pc))}")
    out("SPIKE2 === off")


ui_spike = input_spike  # F10 now runs v2 (the keybind calls impl.ui_spike)


def on_reload() -> None:
    out("=== impl loaded")
    safe(_dump_members)
    out(f"mappings dump: {safe(_dump_mappings)}")
