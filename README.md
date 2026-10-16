# Native Gyro Aim — Borderlands 4

**Native** motion aiming for Borderlands 4 on PC. The real rotation of your controller's gyro is added to the game's
own camera, through the same path as look input (`AddYawInput`/`AddPitchInput`). There is no mouse or stick
emulation: the right stick keeps working alongside it and the button prompts never switch to keyboard/mouse.

Tested on Steam build **25372571**.

## Controllers

| Kind | How the mod reads the gyro | Tested in game | Should work (not verified) |
|---|---|---|---|
| **Generic gyro controller** | Steam Input | **GuliKit TT Max (NS69)** in Switch mode, Bluetooth | Original Switch Pro Controller (same protocol and Steam type as the TT Max), Steam Controller (2026) and other gyro controllers Steam Input recognizes |
| **DualSense** | Direct HID (Steam Input off for PlayStation) or Steam Input | DualSense over Bluetooth and USB, both paths; rumble and adaptive triggers keep working | — |
| **Switch 2 Pro Controller** | Direct HID, through [Switch2Connect](https://github.com/TommyWabg/Switch2Connect) in DualSense mode | Switch 2 Pro Controller | — |

The mod uses Steam Input when it hands a controller to the game. When it hands none (e.g. a DualSense with Steam
Input off, since BL4 supports PlayStation pads natively), it reads the controller's HID directly. The panel's
Diagnostics page shows which source is in use.

## Requirements

- Borderlands 4 (Steam).
- [oak2-mod-manager](https://github.com/bl-sdk/oak2-mod-manager/releases) **v0.3** in the game folder. The installer
  offers to download it for you (official release, checked by SHA-256).
- A controller with a gyro (see [Controllers](#controllers)).
- Generic gyro controller (TT Max): **Switch mode** (double-click Mode) and, in Steam > Settings > Controller,
  **Nintendo Switch** support on.
- DualSense: works with Steam's PlayStation support off for the game (BL4 gets the native pad) or on.
- Switch 2 Pro Controller: Switch2Connect in **PS5/DualSense** mode, with the app's own gyro (mouse/stick) off.
- Don't set up gyro-as-mouse in Steam or another app: the rotation would be doubled.

## Install

1. Close the game. Download `NativeGyro-<version>.zip` from Releases and extract it.
2. Double-click **`Install.cmd`**. The installer window finds the game through Steam (or use **Browse...**), checks
   the folder, the mod manager and whether the game is running, then **Install / Update**. No administrator rights
   are needed unless the game is in a protected folder.
3. Start the game. Gyro is **on** from the first launch.

Updating is the same: run the new version's `Install.cmd`. Your settings, and your choice to keep the mod or the gyro
off, are kept.

Command line alternative, from the extracted folder:
`powershell -ExecutionPolicy Bypass -File install.ps1 [-GameDir "D:\...\Borderlands 4"] [-InstallModManager]`.
Manual install: copy the `NativeGyro` folder into `<game folder>\sdk_mods\` (don't zip or rename it).

## Using it

- **Open the gyro panel during gameplay:** hold **L3 + R3** for half a second (click L3 first: the R3 press is
  then held back from the game, so you don't melee), or press **F8** on the keyboard. The combo can be changed in
  the panel (Advanced > Panel combo).
- **In the panel:** D-pad up/down to move, left/right to change, **LB/RB** for fine steps, **A** to select,
  **B** to go back (and to close on the first page). With a keyboard: arrows, Enter, Esc, and type a number on a
  slider (`2.5` or `2,5`) then Enter. The button hints follow the device you used last. Changes apply immediately
  and are saved when you close the panel.
- While the panel is open the game is paused and neither the controller nor the keyboard/mouse act in game;
  closing it never makes the camera jump and never replays a press.
- The first time you play, a short welcome card shows the gyro state, the detected controller and the combo.

| Panel page | Settings |
|---|---|
| Main | Gyro on/off, activation mode (Always, ADS only, Hold button), sensitivity *Grouped* (one slider for both directions) or *Individual* (horizontal and vertical), ADS multiplier, calibrate now (with progress), controller status |
| Advanced | Invert X/Y, gyro space (Player/Local), automatic calibration, smoothing, tightening, gyro button, panel combo, restore defaults |
| Diagnostics | Controller source (Steam Input / HID), motion packets/s, gyro offset, camera hook state and restart, game build, debug trace, copy diagnostics |

- **Gyro button** (Advanced, none by default): in *Hold button* mode the gyro works only while it is held; in
  *Always* / *ADS only* holding it pauses the gyro so you can re-center the controller — release and it continues
  without a jump. The button keeps its own game action.
- **Calibration:** if the camera drifts slowly with the controller still, use *Calibrate now*: lay the controller
  flat within 5 s, it then measures for 4 s and reports *Calibrated*, or *It moved* / *Not lying flat* (the old
  calibration is kept). Automatic calibration removes drift while a menu, the map or pause is open and the
  controller lies still (never while you aim or while the gyro panel is open).
- All options are also in the console mod menu (`F6`, `mods`), where the keyboard key for the panel can be rebound.

## Uninstall

Run `Install.cmd` and click **Uninstall**. Your gyro settings are kept unless you tick *also delete my gyro
settings*. *Remove oak2-mod-manager* is a separate, confirmed action, because every mod that uses it stops working.
Game files and other mods are never touched.

Command line: `uninstall.ps1 [-GameDir ...] [-RemoveSettings] [-RemoveModManager]`.

## Development

```
build.cmd                                                   (builds and runs the tests)
powershell -ExecutionPolicy Bypass -File scripts\install.ps1      (installs straight from the build)
powershell -ExecutionPolicy Bypass -File scripts\package.ps1      (writes dist\NativeGyro-<version>.zip and the SHA-256s)
```

Before publishing a release: `build.cmd` with no failures, build the zip, send `bl4gyro.dll` to VirusTotal and
publish the SHA-256s with the release.

## Controller diagnostics

`build\release\ttmax-diag.exe hid | sdl | steam` lists the HID interfaces, reads the IMU through SDL3 or through
Steam Input (like BL4 does) and writes evidence to `evidence\`. The guided run is `scripts\phase-a.ps1`; use
`-BluetoothOnly` if you only have Bluetooth.

## Documentation

- `docs/TECHNICAL.md`: architecture, measurements and decisions.
- `docs/LIMITATIONS.md`: hardware, Steam and game limits, and risks.
- `docs/adr/`: decisions that are hard to reverse.
- `evidence/`: results of phases A, B, C and D (CSV, logs and summaries).
- `CONTEXT.md`: glossary.

## License

Open source under the MIT license (`LICENSE`).

## Third party

- GamepadMotionHelpers v10 (MIT, vendored in `third_party/`).
- SDL3 3.4.16 (zlib), fetched at build time; `SDL3.dll` ships in the package for the direct HID reading and is used
  by the diagnostics tool.
- oak2-mod-manager / unrealsdk / pyunrealsdk (LGPL-3.0): not redistributed. The installer can download the official
  release on the user's request.
- Design references: Returnal-Native-Gyro, GyroUE/GyroLib, NeonGyro (MIT) and GyroWiki. No code copied.
