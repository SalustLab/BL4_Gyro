"""Re-analyses a ttmax-diag CSV with a motion-rejecting bias estimate.

usage: python tools/analyze_diag.py evidence/A-<label>.csv
Bias = mean of 'rest' samples whose |gyro| < 2 dps on every axis (so picking up / setting down
the controller does not pollute it). Angles are integrated with the sample clock, camera convention
(yaw right +, pitch up +), like core/gyro.cpp in Local space.
"""
import csv
import math
import sys
from collections import defaultdict


def main(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.reader(f):
            if len(r) == 9 and r[0] != "elapsed_s":
                try:
                    rows.append((float(r[0]), r[1], float(r[2]), *map(float, r[3:9])))
                except ValueError:  # partial last line while the run is still writing
                    pass
    still = [r for r in rows if r[1] == "rest" and all(abs(v) < 2.0 for v in r[3:6])]
    if not still:
        sys.exit("no still rest samples")
    bias = [sum(r[3 + i] for r in still) / len(still) for i in range(3)]
    sd = [math.sqrt(sum((r[3 + i] - bias[i]) ** 2 for r in still) / len(still)) for i in range(3)]
    amag = sum(math.sqrt(r[6] ** 2 + r[7] ** 2 + r[8] ** 2) for r in still) / len(still)
    print(f"samples {len(rows)}, still rest samples {len(still)}")
    print("bias dps  pitch %+.3f yaw %+.3f roll %+.3f" % tuple(bias))
    print("sigma dps pitch %.3f yaw %.3f roll %.3f" % tuple(sd))
    print(f"accel |g| at rest {amag:.4f}")

    turned = defaultdict(lambda: [0.0, 0.0, 0.0])  # yaw, pitch, seconds
    prev = None
    for r in rows:
        if prev is not None:
            dt = r[2] - prev[2]
            if 0 < dt <= 0.1:
                t = turned[r[1]]
                t[0] += -(r[4] - bias[1]) * dt
                t[1] += (r[3] - bias[0]) * dt
                t[2] += dt
        prev = r
    for seg, (yaw, pitch, secs) in turned.items():
        print(f"{seg:8s} yaw {yaw:+8.1f}  pitch {pitch:+8.1f}  over {secs:6.1f} s")
    if "yaw" in turned:
        print(f"yaw scale vs 360: {turned['yaw'][0] / 360:.3f}")
    if "pitch" in turned:
        print(f"pitch scale vs 90: {turned['pitch'][1] / 90:.3f}")


if __name__ == "__main__":
    main(sys.argv[1])
