"""Drives bl4gyro.dll through ctypes exactly like the sdkmod does, using the replay backend.

1 s of a 90 dps right turn (200 Hz, controller flat), sensitivity 2.0, Local space, no auto-calibration:
the camera total must be +180 deg whether the "game" drains it at 30 or 144 frames per second.
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
    dll.bl4gyro_status.argtypes = [ctypes.c_char_p, ctypes.c_int]
    return dll


def run(dll: ctypes.CDLL, csv: Path, log: Path, fps: float) -> float:
    for key, value in (("sens_x", 2.0), ("sens_y", 2.0), ("player_space", 0), ("auto_calibrate", 0)):
        assert dll.bl4gyro_set(key.encode(), value) == 1, key
    dll.bl4gyro_start(str(log), str(csv).encode())
    yaw, pitch, total = ctypes.c_double(), ctypes.c_double(), 0.0
    end = time.perf_counter() + 1.6
    while time.perf_counter() < end:
        dll.bl4gyro_take(0, ctypes.byref(yaw), ctypes.byref(pitch))
        total += yaw.value
        time.sleep(1 / fps)
    dll.bl4gyro_stop()
    dll.bl4gyro_take(0, ctypes.byref(yaw), ctypes.byref(pitch))
    return total + yaw.value


def main() -> int:
    dll = load(sys.argv[1])
    assert dll.bl4gyro_set(b"no_such_setting", 1) == 0
    with tempfile.TemporaryDirectory() as tmp:
        csv = Path(tmp) / "turn.csv"
        rows = ["elapsed_s,segment,sample_t_s,gyro_pitch_dps,gyro_yaw_dps,gyro_roll_dps,accel_x_g,accel_y_g,accel_z_g"]
        rows += [f"{i * 0.005:.3f},yaw,{100 + i * 0.005:.3f},0,-90,0,0,1,0" for i in range(201)]
        csv.write_text("\n".join(rows) + "\n")
        results = {fps: run(dll, csv, Path(tmp) / f"log{fps}.txt", fps) for fps in (30, 144)}
    print("camera yaw by frame rate:", {k: round(v, 4) for k, v in results.items()})
    ok = all(abs(v - 180.0) < 0.01 for v in results.values())
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
