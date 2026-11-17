"""Forecast GTA VI launch-day Twitch viewers, hour by hour (hours 2..24).

Model: anchor on hour 1's print, then apply the launch-day shape learned
from the case's own comparables.  For every comparable past launch we take
its release-day (UTC) hourly counts, divide by its hour-1 count and work in
log space, so the shape is scale-free: a bigger launch keeps the same
ratios, only the anchor changes.  Comparables that cannot anchor the same
way are dropped -- early-access-contaminated launches (their "release day"
is really day 3 or 4 of play) and launches whose hour 1 was still a
pre-unlock trickle (their log-ratio to later hours explodes past 3.5).
The target game's own category history is dropped too (it is pre-release
hype, not a launch).

For each forecast hour we take the median log-ratio across the kept
comparables as the centre and a Gaussian spread from the inter-quartile
range (sigma = IQR / 1.349, floored at 0.15), scaled by SPREAD.  Centre and
spread are smoothed with a 3-hour moving average, because neighbouring
hours share the same unlock wave (Europe waking, US East at 05:00Z, US
West at 08:00Z).  Quantiles: q_tau = p1 * exp(median + z_tau * sigma),
with the standard-normal z for the case's levels.

Deterministic: no randomness, no dict-order dependence (everything is
sorted), no network, stdlib only.  Reads every *.in in the input dir and
writes one *.out per case.
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# Spread calibration (tuned on leave-one-out pinball over the comparables,
# targets restricted to the practice-like family -- rolling-midnight,
# non-early-access launches; the unshrunk IQR spread measured best there,
# 0.3019 vs 0.3065 for the first version's 0.85 shrink, and also better
# on the full 37-game set, 0.8272 vs 0.8408):
# the centre is shrunk 10% toward persistence (flat at hour 1) as a hedge
# against a flatter-than-typical launch day, and sigma is floored so the
# early hours keep an honest minimum width.
SPREAD = 1.0
SIGMA_FLOOR = 0.25
CENTRE_SHRINK = 0.9
# A comparable whose log-ratio ever exceeds this had an hour 1 that was
# still pre-unlock; it cannot anchor a forecast the same way.
MAX_LOG_RATIO = 3.5
MIN_POOL = 5


def parse_time(text):
    """ISO 8601 timestamp -> aware datetime (handles a trailing Z)."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def round2(x):
    """Round half up to 2 decimals; whole numbers come back as ints."""
    scaled = x * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100.0
    return int(value) if value.is_integer() else value


def quantile(sorted_vals, p):
    """Linear-interpolation quantile of an already-sorted list."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_vals[0]
    pos = p * (n - 1)
    lo = int(pos)
    hi = min(n - 1, lo + 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def smooth(values):
    """3-point moving average; ends use the two available points."""
    out = []
    for i in range(len(values)):
        lo = max(0, i - 1)
        hi = min(len(values), i + 2)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def comparable_profiles(case):
    """Log-ratio profiles (hours 1..24 vs hour 1) of usable comparables.

    Returns a list of 24-float lists, one per comparable.
    """
    target_name = (case.get("game") or {}).get("name", "").lower()
    profiles = []
    for comp in case.get("comparables") or []:
        name = (comp.get("name") or "").lower()
        # The target game's own pre-release category history is not a launch.
        if target_name and target_name in name:
            continue
        unlock = (comp.get("unlock") or "").lower()
        # Early-access launches and weak analogues do not share the shape.
        if "early-access" in unlock or "tier: weak" in unlock:
            continue
        day_start = parse_time(comp["day_start"])
        by_hour = {}
        for point in comp.get("hourly") or []:
            try:
                by_hour[parse_time(point["from"])] = point["viewers"]
            except (KeyError, TypeError, ValueError):
                continue
        day = []
        ok = True
        for h in range(24):
            viewers = by_hour.get(day_start + timedelta(hours=h))
            if viewers is None or viewers <= 0:
                ok = False
                break
            day.append(viewers)
        if not ok:
            continue
        hour1 = day[0]
        ratios = [math.log(v / hour1) for v in day]
        # Hour 1 still pre-unlock: the anchor means something else here.
        if max(ratios) > MAX_LOG_RATIO:
            continue
        profiles.append(ratios)
    return profiles


def baseline_quantiles(p1, hour):
    """House persistence fallback: flat median, widening log spread."""
    return [round2(p1 * math.exp(z * 0.15 * math.sqrt(hour - 1))) for z in Z]


def forecast_case(case):
    first = next((k for k in case["known"] if k["hour"] == 1), None)
    if first is None:
        raise ValueError("case has no hour-1 print")
    p1 = max(1, first["viewers"])
    hours = [row["hour"] for row in case["forecast"]]

    profiles = comparable_profiles(case)
    if len(profiles) < MIN_POOL:
        return {"hours": [{"hour": h, "q": baseline_quantiles(p1, h)} for h in hours]}

    centres = []
    sigmas = []
    for h in range(1, 24):  # hours 2..24, index into the 24-long profile
        vals = sorted(prof[h] for prof in profiles)
        centre = quantile(vals, 0.5) * CENTRE_SHRINK
        iqr = quantile(vals, 0.75) - quantile(vals, 0.25)
        sigma = max(SIGMA_FLOOR, iqr / 1.349) * SPREAD
        centres.append(centre)
        sigmas.append(sigma)
    centres = smooth(centres)
    sigmas = smooth(sigmas)

    rows = []
    for i, h in enumerate(range(2, 25)):
        qs = []
        for z in Z:
            q = p1 * math.exp(centres[i] + z * sigmas[i])
            q = min(max(q, 0.01), 1_000_000_000.0)
            qs.append(round2(q))
        # Keep the row non-decreasing after rounding.
        for k in range(1, 5):
            if qs[k] < qs[k - 1]:
                qs[k] = qs[k - 1]
        rows.append({"hour": h, "q": qs})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        out = OUTPUT_DIR / f"{path.stem}.out"
        out.write_text(json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
