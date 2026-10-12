"""Analyses a NativeGyro trace.csv (Debug trace option).

usage: python tools/analyze_trace.py <trace.csv>
P = motion packet (sensor thread), T = camera drain, R = ControlRotation + injected camera delta per frame.
"""
import csv
import math
import sys

STEAM_DPS = 2000.0 / 32768.0


def wrap(d: float) -> float:
    return (d + 180.0) % 360.0 - 180.0


def pct(values, p):
    if not values:
        return float("nan")
    v = sorted(values)
    return v[min(len(v) - 1, int(p * (len(v) - 1)))]


def qmul(a, b):  # (w, x, y, z)
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw)


def rotvec_deg(q):
    w, x, y, z = q
    if w < 0:
        w, x, y, z = -w, -x, -y, -z
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    angle = 2 * math.atan2(n, w)
    return tuple(math.degrees(angle) * c / n for c in (x, y, z))


def main(path: str) -> None:
    P, R = [], []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            try:
                if row[0] == "P":
                    t, rx, ry, rz, ax, ay, az, qx, qy, qz, qw = map(float, row[1:12])
                    P.append((t, (rx, ry, rz), (qw, qx, qy, qz)))
                elif row[0] == "R":
                    R.append((float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]),
                              int(row[6]), int(row[7])))
            except (ValueError, IndexError):
                pass
    span = R[-1][0] - R[0][0] if R else 0
    print(f"packets {len(P)}, frames {len(R)} over {span:.1f} s -> {len(R) / span:.1f} frames/s, {len(P) / span:.1f} packets/s")

    # 1. packet cadence and packets per frame
    pdt = [(b[0] - a[0]) * 1000 for a, b in zip(P, P[1:]) if b[0] - a[0] < 0.1]
    print(f"packet dt ms: p10 {pct(pdt, .1):.1f}  p50 {pct(pdt, .5):.1f}  p90 {pct(pdt, .9):.1f}  p99 {pct(pdt, .99):.1f}")
    per_frame, i = [], 0
    for a, b in zip(R, R[1:]):
        n = 0
        while i < len(P) and P[i][0] < b[0]:
            if P[i][0] >= a[0]:
                n += 1
            i += 1
        per_frame.append(n)
    hist = {k: per_frame.count(k) for k in sorted(set(per_frame))}
    print(f"packets per frame: {hist}")

    # 2. does each injection become ControlRotation change? (gate open on both frames; stick assumed untouched)
    pairs = [(wrap(b[1] - a[1]), a[3], wrap(b[2] - a[2]), a[4]) for a, b in zip(R, R[1:]) if a[5] and b[5]]
    for label, sel in (("all", lambda p: True), ("small |inj|<0.05", lambda p: 0 < abs(p[1]) < 0.05)):
        s = [p for p in pairs if sel(p)]
        inj = sum(p[1] for p in s)
        got = sum(p[0] for p in s)
        print(f"yaw {label}: frames {len(s)}  injected {inj:+.3f}  ControlRotation {got:+.3f}  ratio {got / inj if inj else float('nan'):.3f}")
    inj_p = sum(p[3] for p in pairs)
    got_p = sum(p[2] for p in pairs)
    print(f"pitch all: injected {inj_p:+.3f}  ControlRotation {got_p:+.3f}  ratio {got_p / inj_p if inj_p else float('nan'):.3f}")

    # 3. judder: during motion, how often a frame gets no new rotation
    moving = [p for p in pairs if abs(p[0]) > 0.05 or abs(p[1]) > 0.05]
    zero = [p for p in moving if p[1] == 0 and p[3] == 0]
    print(f"moving frames {len(moving)}, of which {len(zero)} got no gyro delta ({100 * len(zero) / max(1, len(moving)):.0f}%)")

    # 4. rate x dt (what the mod integrates) vs Steam's quaternion (integrates every gyro sample)
    rate_sum = [0.0, 0.0, 0.0]
    quat_sum = [0.0, 0.0, 0.0]
    corr = [[0.0] * 3 for _ in range(3)]
    for a, b in zip(P, P[1:]):
        dt = b[0] - a[0]
        if not 0 < dt < 0.1:
            continue
        rate = [v * STEAM_DPS * dt for v in b[1]]
        qa = a[2]
        dq = qmul((qa[0], -qa[1], -qa[2], -qa[3]), b[2])
        rv = rotvec_deg(dq)
        for k in range(3):
            rate_sum[k] += rate[k]
            quat_sum[k] += rv[k]
            for j in range(3):
                corr[k][j] += rate[k] * rv[j]
    print("rate x dt sum (steam x pitch, y roll, z yaw): " + "  ".join(f"{v:+.1f}" for v in rate_sum))
    print("quaternion delta sum (q x, y, z):             " + "  ".join(f"{v:+.1f}" for v in quat_sum))
    print("cross products rate[k]*quat[j] (find the axis mapping):")
    for k, name in enumerate(("rate x", "rate y", "rate z")):
        print(f"  {name}: " + "  ".join(f"{c:+10.1f}" for c in corr[k]))


if __name__ == "__main__":
    main(sys.argv[1])
