# Native Gyro Aim — technical document

Native gyro aim integration for Borderlands 4 (Steam build 25372571, UE 5.5.4 "+Oak2"), with the GuliKit TT Max
(NS69) as the first target. Evidence: `evidence/PHASE-A.md`, `evidence/PHASE-B.md`, `evidence/PHASE-C.md`,
`evidence/PHASE-D.md`.

## Architecture

```
TT Max (Switch mode) ──BT──► Steam (Switch support) ──► virtual XInput ──► BL4 (buttons, sticks, rumble: unchanged)
                               │
                               └─ ISteamInput::GetMotionData (through the game's own steam_api64.dll)
                                    │ sensor thread in bl4gyro.dll (~660 loops/s)
                                    ▼
             gyro::from_steam → gyro::Processor (GamepadMotionHelpers: calibration + Player Space, optional filters)
                                    │ Processor::rate()  (deg/s, camera convention)
                                    ▼
                       gyro::RateHold (held rate, thread-safe)
                                    │ bl4gyro_take() through ctypes, once per camera update
                                    ▼
        sdk_mods/NativeGyro (Python, oak2-mod-manager): hook /Script/Engine.CameraModifier:BlueprintModifyCamera
          gate + gyro enabled + activation mode → sensitivity/ADS/inversion → AddYawInput(yaw/2.5), AddPitchInput(pitch/−2.5)
          panel.py: UMG panel + keybinds (same camera-update hook, separate hook id)
```

Why this shape:

1. **Framework.** UE4SS does not run on BL4 without a binary patch. bl-sdk (oak2-mod-manager / unrealsdk) maintains
   the signatures of this build (PGO and non-PGO, Denuvo unpack, anti-debug thread).
2. **Sensor through Steam.** The TT Max only exposes its IMU in Switch mode, and BL4 only sees its buttons in that
   mode through Steam Input. With Steam Input active, the overlay hides the physical HID from the game process; the
   source is then the game's own Steam Input API, called through the *flat* exports of `steam_api64.dll`, with no
   Steamworks SDK.
   **HID fallback (SDL3).** When Steam Input hands the game no controller (e.g. a DualSense with Steam Input off,
   since BL4 supports PlayStation pads natively), the DLL reads the pad's HID through SDL3, with only the HIDAPI
   drivers (RawInput/XInput/WGI/GameInput/DirectInput off; LEDs untouched). One source at a time: if a controller
   appears in Steam Input, the HID pad is released. Samples with a repeated `sensor_timestamp` are dropped:
   Switch2Connect repeats one IMU reading (~65 Hz) across 1 kHz reports, and `dt = 0` would zero the held rate
   (measured: 4678 of 5002 samples were repeats). Without game focus, samples are ignored.
3. **Native camera.** `AddYawInput`/`AddPitchInput` are the look input's own path. Measured: exact (×2.5/×−2.5), no
   acceleration/smoothing, applied on the next frame. `SetControlRotation` does not persist: the Gbx camera
   rewrites the rotation.
4. **ctypes.** The C++ stays where the cost is (sensor, filters, timing) and depends on neither Python's ABI nor
   unrealsdk.
5. **Panel in UMG.** BL4 draws no HUD canvas (`HUD:ReceiveDrawHUD` never runs, `evidence/B-calls-summary.txt`); its
   UI is UMG. The panel is a `UserWidget` built by reflection (Border > VerticalBox > TextBlocks) and added to the
   viewport, so the game's renderer draws it with its own DPI scaling. See `docs/adr/0001-panel-rendered-with-umg.md`.

## Components

| File | Role |
|---|---|
| `core/gyro.hpp/.cpp` | SDL/Steam → deg/s and g conversions (SDL axes), `Processor` (incl. manual calibration result), `RateHold`, `to_camera` |
| `core/steam_motion.hpp/.cpp` | ISteamInput through flat exports; `has_data` (all-zero packet = window without focus) |
| `core/bl4gyro.cpp` | `bl4gyro.dll`: sensor thread (Steam Input, HID fallback through SDL3), CSV replay, log, optional trace, C ABI incl. `bl4gyro_info` |
| `mod/NativeGyro/__init__.py` | sdkmod: options, per-frame hook, gate, ADS, states, injection, calibration countdown, first run, migration |
| `mod/NativeGyro/panel.py` | UMG panel, toasts, welcome card, combo / navigation / gyro button input |
| `mod/NativeGyro/state.py` | game-independent logic: injection precedence, combo, key repeat, number parsing, settings recovery and migration, menu model |
| `scripts/installer.ps1`, `scripts/Install.cmd` | installer window (Windows Forms) over `install.ps1` / `uninstall.ps1` |
| `diag/ttmax_diag.cpp` | `ttmax-diag.exe`: `hid`, `sdl`, `steam`, with a guided protocol and CSV evidence |
| `tools/probe/` | in-game probe (dev): injection measurements, call log, members, mappings, gate watch, UI/input spike |
| `tools/analyze_diag.py`, `tools/analyze_trace.py` | offline analysis of the evidence |

## Measured details that define the design

**Axes and units.** `InputMotionData_t.rotVel` maps int16 to ±2000 deg/s; `posAccel` int16 to ±2 g. Mapping to SDL
(X right, Y up, Z toward the player, counter-clockwise positive): pitch = `rotVelX`, yaw = `rotVelZ`,
roll = `+rotVelY`. The roll sign was corrected by measuring the bias on both paths. Accelerometer:
`(posAccelX, posAccelZ, −posAccelY)`.

**Steam and focus.** Steam delivers the controller and its motion only to the focused window
(`OnFocusWindowChanged` in `controller_ui.txt`). Without focus, `GetMotionData` returns an all-zero packet, treated
as "no data".

**Cadence in game.** Inside BL4 Steam updates motion ~48 times/s (the sensor loop runs at ~660/s), with 40–500 ms
gaps about twice a second that don't line up with game hitches. Three delivery versions, compared with the same
criteria on the traces `evidence/C-trace-*.csv`:

| Delivery | Empty frames while moving | Frame-to-frame variation p50 / p90 |
|---|---|---|
| Whole delta on the next frame | 11% | 0.55 / 2.00 |
| Packet spread over the typical interval (`Pacer`, removed) | 2% | 0.22 / 1.24 |
| **Held rate (`RateHold`)** | **0%** | **0.15 / 0.75** |

`RateHold` integrates the last rate over each frame's time, keeps it for at most 100 ms and adds no latency. The
integrated total does not depend on FPS (`dll_replay` test: 180.0° at 30 and at 144 fps).

**Calibration.** The TT Max bias sits around +0.17/−0.33/−0.35 deg/s (pitch/yaw/roll); Steam does not remove it.
With GamepadMotionHelpers' *Stillness* running while aiming, a slow, steady 24° turn comes out as 8.5° (test
`slow_pan_is_kept_while_auto_calibration_is_suspended`). That was the "stuck / sticky directions" symptom. So
automatic calibration runs only with the gate closed and uses *Stillness* only: *SensorFusion* corrects pitch/roll
from the accelerometer, which has a ~9% scale error on this controller and went with the "aim creeping up" symptom.
Residual drift measured in game: −0.013 deg/s pitch, −0.020 deg/s yaw.

Manual calibration ("Calibrate now") starts after a 5 s countdown in the mod ("lay it flat"), so the button press
and putting the controller down are not measured, then measures for 4 s. It counts sensor time, so it only
progresses with motion data. It is rejected and the previous offset restored if the raw rate spreads more than
3 deg/s (*moved*) or gravity is not within ~25° of the controller's up axis (*not flat*): measured in game, a
calibration taken in the hand learned a 0.8 deg/s "bias" from slow hand drift and turned it into a steady camera
drift (`evidence/PHASE-D.md`; tests `calibration_reports_moved_and_keeps_previous_offset`,
`calibration_rejects_slow_turn_and_not_flat`). Without data past its deadline it reports *no data*. Progress,
result and the subtracted offset come from `bl4gyro_info`; `bl4gyro.log` records every result and offset change.

**Gate.** Measured in game: pause, inventory and map menus set `bShowMouseCursor` and `IsGamePaused`.
`IsLookInputIgnored` does not change in those menus, but it is checked. The camera hook keeps running while paused.
ADS comes from `OakCharacter.ZoomState.State` (ZoomingIn/Zoomed), not from the FOV: sprinting alone changes the FOV
by up to 13°. Outside an `OakCharacter`, e.g. in a vehicle, the gyro is off.

**Injection precedence** (`state.should_inject`): gyro disabled, panel open, calibration running and a closed gate
each block injection in every mode. Then *Hold button* needs the gyro button held; in *Always* / *ADS only* a held
gyro button suspends, and *ADS only* needs ADS. The DLL is drained on every camera update in every state, so motion
made while suspended is discarded. Automatic calibration follows the game gate only, and is also off while the
panel is open (the controller is in the hand then): opening the panel or holding the gyro button never runs it.

**Panel input** (measured in game, `evidence/PHASE-D.md`). The installed `keybinds` module hooks
`UGbxEnhancedPlayerInput::InputKey`; a callback that returns `Block` keeps the event from the game. It sees the
keyboard, the mouse and the stick clicks, but not the other pad buttons, and `IsInputKeyDown` doesn't see them
either. So:
- `bl4gyro.dll` reads the pad buttons itself (`bl4gyro_buttons`): SDL when the HID pad is open, otherwise XInput,
  which is Steam Input's virtual pad as the game sees it; 0 while the game is not focused. The panel's D-pad/A/B/
  LB/RB navigation and the gyro button come from it.
- The combo (default L3 + R3, 0.5 s) comes from the hook, which also blocks the second click.
- The panel opens only during gameplay. It pauses the game (`SetGamePaused`) and calls `DisableInput` on the pawn
  and on the player controller: pausing alone still let the trigger fire and View/Menu open game menus. Every
  keyboard/mouse key BL4 maps is blocked through the hook (a mouse click made while paused was replayed on
  unpause); releases always pass. Closing undoes it in reverse. If the game can't be paused (co-op), the pawn's
  move/look input is ignored instead (`SetIgnoreMoveInput/SetIgnoreLookInput`, counted, one `False` per `True`).
- Opening, closing and every panel action run on the next camera update, never inside a keybind callback (keybinds
  must not be registered or removed during the hook's own dispatch). Held-key repeat uses its own timer (0.4 s,
  then every 80 ms). Button hints follow the last device used and name the real buttons: for a Steam Input pad
  the DLL asks Steam which physical button produces the virtual pad's A/B/LB/RB (`GetActionOriginFromXboxOrigin`,
  which follows the user's layout settings such as Nintendo layout); for the HID pad it uses SDL's button labels;
  otherwise the controller family decides.

**Settings.** mods_base saves `sdk_mods/settings/NativeGyro.json` (options by identifier, keybinds, `enabled`) and
only auto-enables a mod whose saved `enabled` is true. The mod enables itself when the file or the key is missing
(first run) and otherwise keeps the user's choice. 0.1 identifiers are kept; `Link vertical` is migrated from
`sens_x == sens_y`. Values read from the file are clamped or reset (`state.sanitize`). Changes are saved 1 s after
the last change and when the panel closes, never per frame. The installer never touches the settings file;
uninstall keeps it unless asked.

**Safe failures.**
- Errors in the camera hook are counted; after 100 in a row the hook removes itself. The panel uses its own hook id,
  so it keeps working, shows a message and offers *Restart gyro* in Diagnostics.
- A build other than the tested one only logs a warning: the whole path is reflection, so missing members become a
  contained error, not a memory write.
- The DLL does not write game memory.

## Build and tests

`build.cmd` uses vswhere + MSVC + CMake/Ninja and runs CTest:
- `core_tests`: conversions, integration, gaps, FPS independence, calibration (incl. result and progress), filters,
  held rate, threads.
- `dll_replay`: ABI through ctypes, replay, exact total at 30 and 144 fps, `bl4gyro_info` source and calibration.
- `mod_logic`: `state.py` outside the game (precedence, combo, repeat, numbers, settings recovery/migration, menu).
- `scripts`: package contents, install/update/uninstall against a fake Steam install, settings kept, oak2 download
  refusals.

SDL3 3.4.16 comes through FetchContent with a pinned SHA-256 (diagnostics and the DLL's HID fallback; `SDL3.dll`,
zlib license, ships in the package next to `bl4gyro.dll`). GamepadMotionHelpers v10 is vendored (MIT).
