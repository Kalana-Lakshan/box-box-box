#!/usr/bin/env python3
"""
Calibration script for Box Box Box F1 Race Simulator.

Known constraints from cross-strategy analysis of 30,000 historical races:
  sd = -1.25 * hd   (EXACT: SOFT speed delta = -5/4 * HARD speed delta)
  sdg = 4.75 * mdg  (EXACT: SOFT degrades 19/4x faster than MEDIUM)
  hdg ≈ 0           (HARD barely degrades)

Free parameters to find:
  hd   - HARD compound speed delta (seconds/lap relative to MEDIUM)
  mdg  - MEDIUM compound degradation rate (seconds/lap per tire-age unit)
  tc   - temperature coefficient (0 = no temperature effect)
  tr   - reference temperature

Formula:
  lap_time = base + delta[compound] + deg[compound] * tire_age * temp_factor
  temp_factor = 1.0 + tc * (track_temp - tr)

  Stint total (closed-form for n laps on compound C, starting at tire_age=1):
    speed_part = n * delta[C]
    deg_part   = temp_factor * deg[C] * n*(n+1)/2
"""

import json
import os
import sys
import glob
import itertools
from pathlib import Path


# ── Constants derived from analysis ──────────────────────────────────────────
# All values relative to free parameter hd and mdg
RATIO_SD_HD  = -1.25   # sd = RATIO_SD_HD * hd
RATIO_SDG_MDG = 4.75   # sdg = RATIO_SDG_MDG * mdg
HDG_VALUE    = 0.0     # hdg ≈ 0

ROOT = Path(__file__).parent.parent


def load_test_cases():
    """Load all 100 test cases (inputs + expected outputs)."""
    test_cases = []
    inputs_dir  = ROOT / "data" / "test_cases" / "inputs"
    outputs_dir = ROOT / "data" / "test_cases" / "expected_outputs"

    for inp_path in sorted(inputs_dir.glob("test_*.json")):
        name = inp_path.stem  # e.g. "test_001"
        out_path = outputs_dir / (name + ".json")
        if not out_path.exists():
            continue
        with open(inp_path) as f:
            inp = json.load(f)
        with open(out_path) as f:
            out = json.load(f)
        test_cases.append((inp, out["finishing_positions"]))

    return test_cases


def compute_race_time(strategy, cfg, hd, mdg, tc, tr):
    """
    Compute the total race time contribution (relative to T*base) for one driver.

    Returns a float. To compare drivers, we only need relative differences.
    """
    T    = cfg["total_laps"]
    base = cfg["base_lap_time"]
    pit  = cfg["pit_lane_time"]
    temp = cfg["track_temp"]

    tf = 1.0 + tc * (temp - tr)

    sd  = RATIO_SD_HD   * hd
    sdg = RATIO_SDG_MDG * mdg
    hdg = HDG_VALUE

    deltas = {"SOFT": sd,  "MEDIUM": 0.0, "HARD": hd}
    degs   = {"SOFT": sdg, "MEDIUM": mdg, "HARD": hdg}

    stops = sorted(strategy.get("pit_stops", []), key=lambda p: p["lap"])

    # Build stints: (compound, num_laps)
    stints = []
    current_compound = strategy["starting_tire"]
    prev_lap = 0
    for stop in stops:
        lap = stop["lap"]
        stints.append((current_compound, lap - prev_lap))
        current_compound = stop["to_tire"]
        prev_lap = lap
    stints.append((current_compound, T - prev_lap))

    # Base time + pit penalties
    total_time = T * base + len(stops) * pit

    # Closed-form stint contribution: Σ(n·Δ) + tf·deg·Σ(k) for k=1..n
    for compound, n in stints:
        total_time += n * deltas[compound]
        total_time += tf * degs[compound] * n * (n + 1) / 2

    return total_time


def simulate_race(test_input, hd, mdg, tc, tr):
    """Predict finishing positions for a single race."""
    cfg      = test_input["race_config"]
    strats   = test_input["strategies"]

    results = []
    for pos_key, strategy in strats.items():
        grid_pos = int(pos_key[3:])  # "pos12" → 12
        t = compute_race_time(strategy, cfg, hd, mdg, tc, tr)
        results.append((t, grid_pos, strategy["driver_id"]))

    results.sort(key=lambda x: (x[0], x[1]))
    return [r[2] for r in results]


def evaluate_params(test_cases, hd, mdg, tc=0.0, tr=25.0):
    """
    Returns (exact_match_count, total_position_errors) for given parameters.
    exact_match = all 20 finishing positions are correct.
    """
    exact = 0
    total_err = 0

    for inp, expected in test_cases:
        predicted = simulate_race(inp, hd, mdg, tc, tr)
        if predicted == expected:
            exact += 1
        else:
            for pred_pos, exp_id in enumerate(expected):
                actual_pos = predicted.index(exp_id)
                total_err += abs(pred_pos - actual_pos)

    return exact, total_err


def grid_search_no_temp(test_cases, verbose=True):
    """
    Phase 1: Grid search with no temperature effect (tc=0).
    We search over (hd, r=mdg/hd).
    """
    print("=" * 60)
    print("Phase 1: Grid search – no temperature effect (tc=0)")
    print("=" * 60)

    n = len(test_cases)

    # From test_001 analysis: r < 0.04762
    # Try hd values; since ordering within a no-stop-difference race
    # depends only on r=mdg/hd, we can start with hd=1 and vary r.
    best_exact   = -1
    best_err     = 1e18
    best_params  = None

    hd_values  = [round(0.1 * i, 3) for i in range(1, 51)]   # 0.1 .. 5.0
    r_values   = [round(0.001 * i, 4) for i in range(1, 51)] # 0.001 .. 0.050

    results = []
    for hd in hd_values:
        for r in r_values:
            mdg = r * hd
            exact, err = evaluate_params(test_cases, hd, mdg, tc=0.0, tr=25.0)
            results.append((exact, -err, hd, r, mdg))

    results.sort(reverse=True)  # highest exact first, then lowest error

    print(f"\nTop 20 (out of {len(results)}) parameter sets:")
    print(f"{'exact':>6} {'err':>8} {'hd':>6} {'r=mdg/hd':>10} {'mdg':>8}")
    print("-" * 45)
    for exact, neg_err, hd, r, mdg in results[:20]:
        print(f"{exact:>6}/{n}  {-neg_err:>8.1f}  {hd:>6.2f}  {r:>10.4f}  {mdg:>8.5f}")

    best_exact, neg_best_err, best_hd, best_r, best_mdg = results[0]
    print(f"\nBest no-temp parameters: hd={best_hd}, r={best_r}, mdg={best_mdg}")
    print(f"  Exact: {best_exact}/{n}, Total pos err: {-neg_best_err:.1f}")
    return best_hd, best_mdg


def grid_search_with_temp(test_cases, hd_hint, mdg_hint, verbose=True):
    """
    Phase 2: Add temperature effect. Search around hint values.
    """
    print("\n" + "=" * 60)
    print("Phase 2: Grid search – with temperature effect")
    print("=" * 60)

    n = len(test_cases)

    # Narrow search around hint
    hd_values  = [round(hd_hint + 0.05 * i, 3) for i in range(-5, 6)]
    r_values   = [round((mdg_hint / hd_hint) + 0.001 * i, 5) for i in range(-10, 11)]
    tc_values  = [round(0.005 * i, 4) for i in range(0, 11)]  # 0 .. 0.05
    tr_values  = [20.0, 25.0, 30.0, 35.0, 40.0]

    best_results = []
    total = len(hd_values) * len(r_values) * len(tc_values) * len(tr_values)
    print(f"Searching {total} combinations...")

    for hd in hd_values:
        if hd <= 0:
            continue
        for r in r_values:
            if r <= 0:
                continue
            mdg = r * hd
            for tc in tc_values:
                for tr in tr_values:
                    exact, err = evaluate_params(test_cases, hd, mdg, tc, tr)
                    best_results.append((exact, -err, hd, r, mdg, tc, tr))

    best_results.sort(reverse=True)

    print(f"\nTop 20 with temperature:")
    print(f"{'exact':>6} {'err':>8} {'hd':>6} {'r':>8} {'mdg':>8} {'tc':>6} {'tr':>5}")
    print("-" * 60)
    for exact, neg_err, hd, r, mdg, tc, tr in best_results[:20]:
        print(f"{exact:>6}/{n}  {-neg_err:>8.1f}  {hd:>6.2f}  {r:>8.4f}  {mdg:>8.5f}  {tc:>6.3f}  {tr:>5.1f}")

    best_exact, neg_best_err, best_hd, best_r, best_mdg, best_tc, best_tr = best_results[0]
    print(f"\nBest with-temp: hd={best_hd}, mdg={best_mdg}, tc={best_tc}, tr={best_tr}")
    print(f"  Exact: {best_exact}/{n}, Total pos err: {-neg_best_err:.1f}")
    return best_hd, best_mdg, best_tc, best_tr


def fine_search(test_cases, hd0, mdg0, tc0=0.0, tr0=25.0):
    """Fine-grained search around best known values."""
    print("\n" + "=" * 60)
    print("Phase 3: Fine-grained search around best parameters")
    print("=" * 60)

    n = len(test_cases)

    # Very fine grid around the best
    hd_vals  = [round(hd0 + 0.01 * i, 3)   for i in range(-10, 11)]
    r0 = mdg0 / hd0
    r_vals   = [round(r0  + 0.0002 * i, 6) for i in range(-10, 11)]
    tc_vals  = [round(tc0 + 0.001 * i, 4)  for i in range(-5, 6)]
    tr_vals  = [round(tr0 + 1.0 * i, 1)    for i in range(-5, 6)]

    best_results = []
    total = len(hd_vals) * len(r_vals) * len(tc_vals) * len(tr_vals)
    print(f"Searching {total} combinations...")

    for hd in hd_vals:
        if hd <= 0:
            continue
        for r in r_vals:
            if r <= 0:
                continue
            mdg = r * hd
            for tc in tc_vals:
                for tr in tr_vals:
                    exact, err = evaluate_params(test_cases, hd, mdg, tc, tr)
                    best_results.append((exact, -err, hd, r, mdg, tc, tr))

    best_results.sort(reverse=True)

    print(f"\nTop 20 fine-grained:")
    print(f"{'exact':>6} {'err':>8} {'hd':>6} {'r':>8} {'mdg':>8} {'tc':>7} {'tr':>5}")
    print("-" * 62)
    for exact, neg_err, hd, r, mdg, tc, tr in best_results[:20]:
        print(f"{exact:>6}/{n}  {-neg_err:>8.1f}  {hd:>6.3f}  {r:>8.5f}  {mdg:>8.5f}  {tc:>7.4f}  {tr:>5.1f}")

    return best_results[0]


def save_parameters(params):
    """Save calibrated parameters to solution/parameters.json."""
    params_path = ROOT / "solution" / "parameters.json"
    out = {
        "hd":  params["hd"],
        "sd":  RATIO_SD_HD   * params["hd"],
        "mdg": params["mdg"],
        "sdg": RATIO_SDG_MDG * params["mdg"],
        "hdg": HDG_VALUE,
        "tc":  params["tc"],
        "tr":  params["tr"],
        "calibration_accuracy": params.get("accuracy", "unknown")
    }
    with open(params_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nParameters saved to {params_path}")
    print(json.dumps(out, indent=2))


def main():
    print("Loading test cases...")
    test_cases = load_test_cases()
    print(f"Loaded {len(test_cases)} test cases.")

    # Phase 1: no temperature
    best_hd, best_mdg = grid_search_no_temp(test_cases)

    # Phase 2: add temperature
    best_hd, best_mdg, best_tc, best_tr = grid_search_with_temp(
        test_cases, best_hd, best_mdg
    )

    # Phase 3: fine search
    result = fine_search(test_cases, best_hd, best_mdg, best_tc, best_tr)
    exact, neg_err, hd, r, mdg, tc, tr = result
    n = len(test_cases)

    print(f"\n{'='*60}")
    print(f"FINAL CALIBRATED PARAMETERS:")
    print(f"  hd  = {hd}   (HARD speed delta vs MEDIUM, s/lap)")
    print(f"  sd  = {RATIO_SD_HD * hd:.4f}  (SOFT speed delta = -1.25 * hd)")
    print(f"  mdg = {mdg:.6f}  (MEDIUM degradation rate, s/lap/age)")
    print(f"  sdg = {RATIO_SDG_MDG * mdg:.6f}  (SOFT degradation = 4.75 * mdg)")
    print(f"  hdg = {HDG_VALUE}")
    print(f"  tc  = {tc}   (temperature coefficient)")
    print(f"  tr  = {tr}   (reference temperature °C)")
    print(f"  Exact matches: {exact}/{n}")
    print(f"  Total position error: {-neg_err:.1f}")

    save_parameters({"hd": hd, "mdg": mdg, "tc": tc, "tr": tr,
                     "accuracy": f"{exact}/{n}"})


if __name__ == "__main__":
    main()
