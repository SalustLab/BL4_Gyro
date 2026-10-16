# Limitations and risks

## Generic gyro controller (tested: GuliKit TT Max)

Mode for controllers read through Steam Input. The TT Max in Switch mode is the tested controller; the items below
are about it. The **original Switch Pro Controller** uses the same protocol and the same Steam type
(`SwitchProController`) and should work the same, probably with a better accelerometer (factory calibration), but it
was not verified.

- **Gyro only in Switch mode.** In PC (XInput) mode the controller sends no IMU data to the PC; its built-in "Motion
  Aim Assist" only moves the right stick. Measured over Bluetooth (`evidence/PHASE-A.md`).
- **Digital triggers in Switch mode.** The Pro Controller protocol sends ZL/ZR as bits. There is no mode with analog
  triggers and gyro at the same time. USB and 2.4 GHz were not tested (no cable or dongle).
- **Back buttons** (G1–G4) are not exposed as their own buttons in any mode, only through firmware remapping.
- **Accelerometer with ~9% scale error** (1.09 g at rest). Only the direction of gravity is used (Player Space), and
  calibration does not use the accelerometer.

## Steam and other controllers

- **Two motion sources.** If Steam Input hands a controller to the game, it is used. If it hands none (e.g. a
  DualSense with Steam Input off), the mod reads the HID directly through SDL3 (Diagnostics shows "HID (SDL)"). With
  Steam Input on for PlayStation, the DualSense goes through Steam (tested in game, ~48 readings/s, same axis signs
  as the Pro Controller).
- **Switch 2 Pro Controller through Switch2Connect** (DualSense USB mode, Steam Input off for PlayStation): tested in
  game, ~65 readings/s over HID (the IMU repeats its reading across the 1 kHz reports).
- **Original DualSense** with Steam Input off for PlayStation: tested in game over Bluetooth (~630 readings/s over
  HID) and USB (~250 readings/s); rumble (haptics) and adaptive triggers keep working with the mod on.
- **Steam Input is required** for the TT Max in Switch mode: it translates buttons, sticks and rumble for BL4, and
  it is the motion source in game. "Nintendo Switch" must be on in Steam > Settings > Controller. The gyro output of
  BL4's default template is already "none"; don't set gyro-as-mouse in Steam, or the rotation doubles.
- **Motion only while the game has focus.** Switching windows stops the gyro, and automatic calibration in menus
  also needs the game in focus. A calibration started without motion data reports "No motion data" and finishes
  once data arrives.
- **~48 readings/s in game**, with 40–500 ms gaps about twice a second. Rate hold hides this, but very sharp turns
  inside a gap (up to 100 ms) use the previous speed until the next reading. Outside the game the same controller
  gives ~830 samples/s through SDL.
- **Controller model names.** The panel shows what the source reports: a Steam Input type (e.g. a Switch-type pad)
  or SDL's pad type. A generic controller such as the TT Max is shown as the type it emulates, not by its brand.

## Panel and input

- **The panel is drawn with the game's UMG UI** (created by reflection, `docs/adr/0001-panel-rendered-with-umg.md`).
  A game patch that changes the UMG classes could stop it from opening; the console mod menu (`F6`, `mods`) keeps
  every option available.
- **Controller buttons can't be held back from the game.** BL4 reads the pad through a path the mod's input hook
  doesn't see (except the stick clicks), so the DLL reads the buttons itself. The panel therefore opens only during
  gameplay and, while open, pauses the game and disables the pawn's and the player controller's input; keyboard and
  mouse keys are blocked through oak2's keybinds hook (key releases always pass, so nothing stays held).
- **The combo's first button reaches the game.** With L3 + R3, the first button pressed acts in game (L3 = sprint,
  R3 = melee) before the second is held back; press L3 first. While L3 is held (e.g. holding sprint), an R3 press is
  held back from the game, so melee does not fire then. The other combos (LT + D-pad Up, View + Menu, LB + RB)
  reach the game with both buttons.
- **The gyro button is not held back from the game**: pick a button whose game action you don't mind (or a back
  paddle mapped to an otherwise unused button).
- **Online co-op:** if the game can't be paused, the panel only keeps the character from moving and looking.
- **No left-stick navigation** in the panel: the D-pad navigates.
- **Key rebinding in the panel** is a list of buttons (raw key capture is not part of oak2-mod-manager v0.3). The
  keyboard key is rebound in the console mod menu.

## Game

- **Tested build: Steam 25372571.** Another build logs a warning. Injection uses reflection, but a change to BL4's
  input scales (today ×2.5 / ×−2.5) would change the sensitivity: re-measure with `tools/probe`.
- **Depends on oak2-mod-manager.** A BL4 patch can break it until bl-sdk updates it. The game then starts without
  mods.
- **Gyro off when not on foot** (vehicles), and also with a visible cursor, when paused, with look input ignored or
  with the camera away from the character.
- **Tested in game** (`evidence/PHASE-C.md`): gyro + stick, ADS, menus/map/inventory, weapon swap, rumble, prompts,
  controller reconnect, disabling/re-enabling the mod, death/loading, install from the release zip (no `-GameDir`).
  Phase D (panel, installer, modes) status is in `evidence/PHASE-D.md`.
- **Not tested:** vehicles, cutscenes and dialogue, co-op, Epic Store, original Pro Controller and Steam Controller
  (2026) (they should work through Steam Input or HID, but were not verified), long sessions (>1.5 h), replay with
  FPS locked to 30/60/144 in game (covered only by the DLL test).
- **Online co-op:** Take-Two states it does not act against single-player, non-commercial mods. Play offline or in a
  solo session; a mod that touches aiming in a public match may be seen as an advantage.

## Project

- Default sensitivity 2.0 (the tester plays at 3.0) and smoothing/tightening off are values chosen by a single
  tester, not generally validated parameters.
- Not implemented (out of scope): toggle mode, ratchet beyond the hold-to-suspend gyro button, World Space,
  flick stick, acceleration, per-weapon profiles and FOV scaling.
