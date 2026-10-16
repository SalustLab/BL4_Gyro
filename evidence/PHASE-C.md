# Phase C — playable vertical slice (MVP), validated in game (2026-10-11)

Setup: Borderlands 4 Steam build 25372571, oak2-mod-manager v0.3, NativeGyro 0.1.0 (`7494c04`), GuliKit TT Max in
Switch mode over Bluetooth, Steam Input with "Nintendo Switch" support, BL4's default Switch Pro template (no gyro
output). Tester: the project owner, playing single player with OptiScaler frame generation (~45–53 game fps).

## Iterations driven by in-game evidence

| Build | Tester report | Measured cause | Fix |
|---|---|---|---|
| `4e057ea` (first in-game) | "rotation feels stuck", "directions locked", "aim creeps up" | Stillness auto-calibration during aiming ate slow steady motion (24° → 8.5° in a unit test); SensorFusion + 9%-off accelerometer suspected for the pitch creep; Steam motion only ~48/s → 39% of frames with no rotation (`C-trace-1.csv`) | `0c93686`: auto-calibration only while the gate is closed, Stillness only; Debug trace |
| `0c93686` | "not creeping up any more"; still judder | in-game drift after menu calibration −0.013 °/s pitch, −0.020 °/s yaw; judder from delivery timing | `ad63aa7`: paced delivery |
| `ad63aa7` | "better, still a bit stuck"; sensitivity too high (chose 1.25) | Steam skips updates: 146 gaps of 40–500 ms in 69 s, only 2 matching game hitches (`C-trace-2-paced.csv`) → stall + catch-up | `7494c04`: held angular velocity integrated at frame time; default sensitivity 1.25 |
| `7494c04` | **"agora sim … é um gyro de respeito"** | `C-trace-3-ratehold.csv`: 0% empty frames in motion | — |

Smoothness, same criterion on all traces (frames where the 7-frame mean rotation > 0.08°):

| Trace | Motion frames | Empty frames | Frame-to-frame relative change p50 / p90 / p99 |
|---|---|---|---|
| C-trace-1 (immediate hand-off) | 754 | 11% | 0.55 / 2.00 / 2.00 |
| C-trace-2 (paced) | 1940 | 2% | 0.22 / 1.24 / 2.00 |
| C-trace-3 (rate hold, final) | 3155 | **0%** | **0.15 / 0.75 / 1.52** |

Injection fidelity (`C-trace-1.csv`, gate open, sticks untouched): ControlRotation follows the injected yaw on the
next frame with lag 0 (rms residual 0.044° vs 0.33° signal); BL4 adds no smoothing to `AddYawInput`.

## Functional checklist (tester, final build)

| Check | Result |
|---|---|
| Gyro and right stick at the same time | ✓ |
| ADS (camera follows gyro while aiming) | ✓ |
| Pause menu / inventory / map: gyro blocked | ✓ (also measured: gate flags in `PHASE-B.md`) |
| No drift creep after calibration | ✓ |
| Weapon switch | ✓ nothing odd |
| Vibration | ✓ still works |
| Button prompts stay controller (no KBM flip) | ✓ |
| Controller off/on mid-game | ✓ `bl4gyro.log`: disconnected 23:57:28, reconnected 23:57:40, gyro back |
| Disable mod in game (mods → D) | ✓ camera normal; log: hook removed, sensor thread stopped; re-enable (E) clean |
| Death/respawn or loading screen | ✓ |

## Not executed in game

- Replay of the same motion with the FPS capped at 30/60/144 (the DLL-level `dll_replay` test proves the integration
  is frame-rate independent: 180.0° at 30 and 144 fps; the in-game injection was shown exact per frame).
- Vehicles, cutscenes, co-op, sessions longer than ~1.5 h.

## Release package install test (2026-10-12)

Package `NativeGyro-0.1.0.zip` (`0c294c4`, zip SHA-256 `990AF939…6E13`, DLL `5CE58D68…99E8`) on the real game, after
`uninstall.ps1` (oak2 kept, mod and its settings removed, as a new player would have it).

| Check | Result |
|---|---|
| `install.ps1` from the extracted zip, without `-GameDir` | ✓ found `F:\SteamLibrary\...\Borderlands 4` (Steam has another library on an unplugged drive `I:`) |
| Installed files identical to the zip | ✓ SHA-256 match |
| Mod enabled in game, gyro working (TT Max, Switch mode) | ✓ tester |
| TT Max in Windows/PC (XInput) mode | no gyro, as expected: `bl4gyro.log` `connected: XBoxOne (3)` → `0 motion packets/s` (Phase A limitation) |
| `bl4gyro.dll` imports | `KERNEL32.dll` only (static CRT), no VC++ runtime needed |

Next: original Switch Pro Controller and DualSense.

## HID fallback: Switch 2 Pro Controller via Switch2Connect (2026-10-15)

Setup: Switch 2 Pro Controller through Switch2Connect emulating a USB DualSense (`054C:0CE6`), Steam
"PlayStation Controller Support" = enabled only in games without support (so Steam Input is off for BL4).

| Build | Tester report | Measured cause | Fix |
|---|---|---|---|
| `79b49d1`-era DLL (Steam Input only) | "não funcionou" | `bl4gyro.log`: `no controller \| 0 motion packets/s`; Steam Input gives the game 0 controllers | SDL3 HID fallback when Steam Input has no controller |
| HID fallback, first build | works, but "terrível, travado, mal mexe" | 1000 packets/s; `ttmax-diag sdl --rest 5`: 4678 of 5002 samples with `dt = 0` (one IMU reading, ~15 ms apart, repeated over 1 kHz reports); each repeat zeroed the held rate | drop samples whose `sensor_timestamp` repeats |
| HID fallback, dedupe | **"ficou ótimo"** | `bl4gyro.log`: `ps5 (HID) \| 65–67 motion packets/s` | — |

At rest via SDL (same controller): bias pitch +0.001, yaw −0.020 °/s; noise σ ≤ 0.12 °/s; accel 1.02 g.
Periods of `0 motion packets/s` in the log are the game out of focus (samples are dropped then).

## HID fallback: genuine DualSense over Bluetooth (2026-10-15)

Same build (HID fallback with dedupe), Switch2Connect off, Steam Input off for PlayStation.

| Check | Result |
|---|---|
| `ttmax-diag sdl --rest 5` | 630 samples/s, 0 repeated timestamps, bias ≤ 0.14 °/s, σ ≤ 0.10 °/s, accel 0.98 g |
| `bl4gyro.log` in game | `ps5 (HID) \| 618–641 motion packets/s` |
| Gyro aim (tester) | ✓ **"funcionou perfeitamente"** |
| Haptics and adaptive triggers with SDL reading the pad | ✓ unaffected |
| Same pad over USB (BT off, cable) | ✓ tester "funcionou sem problemas"; `bl4gyro.log`: `ps5 (HID) \| 250 motion packets/s` |
| Same pad with Steam Input on for PlayStation | ✓ tester "funcionou sem problemas"; `bl4gyro.log`: `connected: PS5 (13)`, `PS5 \| 47–49 motion packets/s`; HID not opened (Steam first). `from_steam` axis signs hold for the DualSense too |
