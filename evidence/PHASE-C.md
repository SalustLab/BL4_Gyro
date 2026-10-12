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
