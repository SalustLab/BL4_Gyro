"""Drives bl4gyro.dll through ctypes exactly like the sdkmod does, using the replay backend.

1 s of a 90 dps right turn (200 Hz, controller flat), sensitivity 2.0, Local space, no auto-calibration:
the camera total must be +180 deg whether the "game" drains it at 30 or 144 frames per second.
Also checks bl4gyro_info: the replay source and a manual calibration that finishes with result "ok".
usage: python dll_replay_check.py <path to bl4gyro.dll>
"""
import ctypes
import sys
import tempfile
import time
from pathlib import Path


def load(path: str) -> ctypes.CDLL:
    dll = ctypes.CDLL(path)
    dll.bl4gyro_start.argtypes = [ctypes.c_wchar_p, ctypes.c_char_p]
    dll.bl4gyro_set.argtypes = [ctypes.c_char_p, ctypes.c_double]
    dll.bl4gyro_set.restype = ctypes.c_int
    dll.bl4gyro_take.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)]
    dll.bl4gyro_stop.restype = None
    dll.bl4gyro_calibrate.argtypes = [ctypes.c_double]
    dll.bl4gyro_calibrate.restype = None
    dll.bl4gyro_trace_line.argtypes = [ctypes.c_char_p]
    dll.bl4gyro_trace_line.restype = None
    dll.bl4gyro_status.argtypes = [ctypes.c_char_p, ctypes.c_int]
    dll.bl4gyro_status.restype = ctypes.c_int
    dll.bl4gyro_info.argtypes = [ctypes.POINTER(ctypes.c_double), ctypes.c_int]
    dll.bl4gyro_info.restype = ctypes.c_int
    dll.bl4gyro_buttons.argtypes = []
    dll.bl4gyro_buttons.restype = ctypes.c_uint
    dll.bl4gyro_stick.argtypes = [ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)]
    dll.bl4gyro_stick.restype = ctypes.c_int
    dll.bl4gyro_button_names.argtypes = [ctypes.c_char_p, ctypes.c_int]
    dll.bl4gyro_button_names.restype = ctypes.c_int
    return dll


def info(dll: ctypes.CDLL) -> list[float]:
    values = (ctypes.c_double * 8)()
    return list(values[: dll.bl4gyro_info(values, 8)])


def run(dll: ctypes.CDLL, csv: Path, log: Path, fps: float, calibrate: float = 0) -> tuple[float, list[float]]:
    for key, value in (("sens_x", 2.0), ("sens_y", 2.0), ("player_space", 0), ("auto_calibrate", 0)):
        assert dll.bl4gyro_set(key.encode(), value) == 1, key
    dll.bl4gyro_start(str(log), str(csv).encode())
    if calibrate:
        dll.bl4gyro_calibrate(calibrate)
    yaw, pitch, total = ctypes.c_double(), ctypes.c_double(), 0.0
    end = time.perf_counter() + 1.6
    while time.perf_counter() < end:
        dll.bl4gyro_take(0, ctypes.byref(yaw), ctypes.byref(pitch))
        total += yaw.value
        time.sleep(1 / fps)
    last_info = info(dll)
    assert dll.bl4gyro_buttons() == 0  # replay: no pad read
    x, y = ctypes.c_double(1), ctypes.c_double(1)
    assert dll.bl4gyro_stick(ctypes.byref(x), ctypes.byref(y)) == 0 and x.value == y.value == 0  # replay: no pad read
    assert dll.bl4gyro_button_names(ctypes.create_string_buffer(64), 64) == 0  # no pad: names unknown
    dll.bl4gyro_stop()
    dll.bl4gyro_take(0, ctypes.byref(yaw), ctypes.byref(pitch))
    return total + yaw.value, last_info


def main() -> int:
    dll = load(sys.argv[1])
    assert dll.bl4gyro_set(b"no_such_setting", 1) == 0
    with tempfile.TemporaryDirectory() as tmp:
        csv = Path(tmp) / "turn.csv"
        rows = ["elapsed_s,segment,sample_t_s,gyro_pitch_dps,gyro_yaw_dps,gyro_roll_dps,accel_x_g,accel_y_g,accel_z_g"]
        rows += [f"{i * 0.005:.3f},yaw,{100 + i * 0.005:.3f},0,-90,0,0,1,0" for i in range(201)]
        csv.write_text("\n".join(rows) + "\n")
        results = {fps: run(dll, csv, Path(tmp) / f"log{fps}.txt", fps)[0] for fps in (30, 144)}
        still = Path(tmp) / "still.csv"
        still.write_text("\n".join(rows[:1] + [f"{i * 0.005:.3f},still,{100 + i * 0.005:.3f},0.5,-1,0.2,0,1,0"
                                               for i in range(201)]) + "\n")
        _, calibrated = run(dll, still, Path(tmp) / "logcal.txt", 60, calibrate=0.5)
    print("camera yaw by frame rate:", {k: round(v, 4) for k, v in results.items()})
    print("info after calibration:", calibrated)
    ok = all(abs(v - 180.0) < 0.01 for v in results.values())
    ok &= calibrated[0] == 3 and calibrated[3] == 1.0 and calibrated[4] == 2  # replay, finished, ok
    ok &= abs(calibrated[6] + 1.0) < 0.05  # offset = the still yaw rate
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
