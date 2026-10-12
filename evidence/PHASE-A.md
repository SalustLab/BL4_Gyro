# Phase A — TT Max hardware feasibility (2026-10-11)

Controller: GuliKit TT Max (NS69), Bluetooth only (no USB cable / 2.4 GHz dongle available for testing).
Tool: `ttmax-diag` (SDL 3.4.16) + `tools/analyze_diag.py` (bias from still rest samples only).
Raw data: `A-*.csv` (one row per IMU sample), per-run summaries `A-*.txt`, `live.log`.

## Result matrix

| Case | Enumerates as | Real IMU | Rate | Triggers | Bias p/y/r (dps) | Noise σ (dps) |
|---|---|---|---|---|---|---|
| Switch mode, BT, direct (`switch-bt`) | 057E:2009 "Nintendo Switch Pro Controller" (HID "Wireless Gamepad", 213-byte descriptor) | **yes** gyro + accel | ~830 samples/s (3 per report); arrival p99 9 ms, gaps up to 60–70 ms | digital (2 values) | +0.188 / −0.310 / −0.379 | 0.05 / 0.11 / 0.06 |
| PC mode, BT (`pc-bt`) | 045E:02FD "Xbox One S Controller" (XInput#0) | **no** | — | analog (73–88 values) | — | — |
| Switch mode, BT, Steam open + Switch support on, direct (`switch-steam`) | same as `switch-bt` | **yes** (a second reader coexists with Steam) | ~830 samples/s | digital | +0.221 / −0.338 / −0.402 | 0.05 / 0.24 / 0.07 |
| Switch mode, BT, via Steam Input API as Borderlands 4 (`switch-steam-api`) | Steam type 10 SwitchProController | **yes** | ~250–270 packets/s **only while the app window is focused** | n/a | +0.158 / −0.362 / −0.404 | 0.06 / 0.11 / 0.06 |

Scale / sign checks (camera convention: yaw right +, pitch up +):

- `switch-bt`: 360° clockwise turn measured **+360.6°** (scale 1.002); "stand upright" measured +95.4°.
- `switch-steam`: a second hand-made turn measured +344.6° (the turn most likely stopped short); upright +95.1°.
- `switch-steam-api`: upright +84.7°; the yaw turn step was skipped. Yaw/pitch/roll signs are confirmed indirectly: the rest bias, a fixed property of the sensor, has the same sign and magnitude as the direct SDL read on all three axes once roll is mapped as `+rotVelY` (fixed in `core/gyro.cpp`).

## Findings

1. **Only Switch mode exposes the gyro.** PC (XInput) mode has analog triggers but no motion data; Switch mode has motion data but digital ZL/ZR. No mode gives both (USB and 2.4 GHz untested).
2. **Steam hands the controller to the focused window only.** With the app unfocused, `GetConnectedControllers` returns nothing at start, and `GetMotionData` returns an all-zero packet once a controller was active. Steam's log shows `OnFocusWindowChanged to game window type: AppID 1285190` when focus returns. In game this pauses the gyro on alt-tab; the backend must treat an all-zero packet as "no data" (`steam::has_data`).
3. **Steam does not calibrate the gyro it reports**: its rest bias equals the raw SDL bias. Calibration is the mod's job.
4. **Uncalibrated drift ≈ 19–22°/min in yaw** (bias −0.31…−0.36 dps). Auto + manual calibration are required.
5. **SDL 3.4.16 timestamps**: the Switch driver assumes 5 ms per IMU sample until it has measured 1000 samples; the TT Max sends ~830/s over BT, so the first ~1.2 s after connecting are time-stretched ×4. Not used in game (Steam path uses the host clock), but relevant to any SDL-based reader.
6. **Accelerometer reads 1.09 g at rest** (≈9% high). Only the gravity *direction* is used (Player Space), so this does not affect aim.
7. Motion Aim Assist (controller-side motion → right stick) was not observed in PC mode; it was most likely not enabled.

## Not tested

USB and 2.4 GHz connections (latency, extra HID interfaces in PC mode); the 5-minute drift run; reconnect during a run.
