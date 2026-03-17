#!/usr/bin/env python3
"""
Calibration using lap-by-lap simulation (not closed form).
The key insight: floating-point accumulation in lap-by-lap simulation creates
tiny but deterministic differences for mirror strategy pairs.

The formula: lap_time = base + delta[C] + deg[C] * tire_age * tf
where tf = 1 + tc * (track_temp - tr)

Parameters to find: hd, sd, mdg, sdg, hdg (and tc, tr)
Known constraints: sd = -1.25*hd, sdg = 4.75*mdg, hdg = ?
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
RATIO_SD_HD = -1.25
RATIO_SDG_MDG = 4.75


def compute_race_time_lapbylap(strategy, cfg, hd, mdg, hdg, tc, tr):
    """Lap-by-lap simulation to get exact floating-point result."""
    T = cfg["total_laps"]
    base = cfg["base_lap_time"]
    pit = cfg["pit_lane_time"]
    temp = cfg["track_temp"]
    tf = 1.0 + tc * (temp - tr)

    sd = RATIO_SD_HD * hd
    sdg = RATIO_SDG_MDG * mdg
    # hdg is a free parameter now

    deltas = {"SOFT": sd, "MEDIUM": 0.0, "HARD": hd}
    degs = {"SOFT": sdg, "MEDIUM": mdg, "HARD": hdg}

    stops = {s["lap"]: s["to_tire"]
             for s in strategy.get("pit_stops", [])}

    total_time = 0.0
    tire_age = 0
    compound = strategy["starting_tire"]

    for lap in range(1, T + 1):
        if lap in stops:
            total_time += pit
            compound = stops[lap]
            tire_age = 0
        tire_age += 1
        total_time += base + deltas[compound] + degs[compound] * tire_age * tf

    return total_time


def simulate(test_input, hd, mdg, hdg, tc, tr):
    cfg = test_input["race_config"]
    strats = test_input["strategies"]
    results = []
    for pos_key, strategy in strats.items():
        grid_pos = int(pos_key[3:])
        t = compute_race_time_lapbylap(strategy, cfg, hd, mdg, hdg, tc, tr)
        results.append((t, grid_pos, strategy["driver_id"]))
    results.sort(key=lambda x: (x[0], x[1]))
    return [r[2] for r in results]


def evaluate(test_cases, hd, mdg, hdg, tc, tr):
    exact = 0
    total_err = 0
    for inp, expected in test_cases:
        pred = simulate(inp, hd, mdg, hdg, tc, tr)
        if pred == expected:
            exact += 1
        else:
            for pp, ep in enumerate(expected):
                ap = pred.index(ep)
                total_err += abs(pp - ap)
    return exact, total_err


def load_test_cases():
    test_cases = []
    inputs_dir = ROOT / "data" / "test_cases" / "inputs"
    outputs_dir = ROOT / "data" / "test_cases" / "expected_outputs"
    for inp_path in sorted(inputs_dir.glob("test_*.json")):
        name = inp_path.stem
        out_path = outputs_dir / (name + ".json")
        if not out_path.exists():
            continue
        with open(inp_path) as f:
            inp = json.load(f)
        with open(out_path) as f:
            out = json.load(f)
        test_cases.append((inp, out["finishing_positions"]))
    return test_cases


def main():
    test_cases = load_test_cases()
    print(f"Loaded {len(test_cases)} test cases")

    # Phase 1: grid search with hdg as free parameter (no temp)
    print("\n=== Phase 1: grid search including hdg (no temp) ===")
    hd_values = [round(0.2 * i, 2) for i in range(1, 26)]  # 0.2..5.0
    r_values = [round(0.002 * i, 4) for i in range(1, 31)]  # 0.002..0.06
    hdg_values = [0.0, 0.01, 0.02, 0.03, 0.05, 0.08, 0.1, 0.15, 0.2]  # absolute hdg values

    best_results = []
    total = len(hd_values) * len(r_values) * len(hdg_values)
    print(f"Searching {total} combinations...")

    for hd in hd_values:
        for r in r_values:
            mdg = r * hd
            for hdg in hdg_values:
                exact, err = evaluate(test_cases, hd, mdg, hdg, 0.0, 25.0)
                best_results.append((exact, -err, hd, r, mdg, hdg))

    best_results.sort(reverse=True)
    print(f"\nTop 20:")
    print(f"{'exact':>6} {'err':>8} {'hd':>6} {'r':>8} {'mdg':>8} {'hdg':>6}")
    for exact, neg_err, hd, r, mdg, hdg in best_results[:20]:
        print(f"{exact:>6}/100  {-neg_err:>8.0f}  {hd:>6.2f}  {r:>8.4f}  {mdg:>8.5f}  {hdg:>6.3f}")

    best_hd = best_results[0][2]
    best_mdg = best_results[0][4]
    best_hdg = best_results[0][5]
    print(f"\nBest: hd={best_hd}, mdg={best_mdg}, hdg={best_hdg}")

    # Phase 2: fine search around best
    print("\n=== Phase 2: fine search including temperature ===")
    hd0, mdg0, hdg0 = best_hd, best_mdg, best_hdg

    hd_vals = [round(hd0 + 0.05 * i, 3) for i in range(-5, 6)]
    r0 = mdg0 / hd0
    r_vals = [round(r0 + 0.001 * i, 5) for i in range(-10, 11)]
    hdg_vals = [round(hdg0 + 0.01 * i, 4) for i in range(-5, 6) if hdg0 + 0.01*i >= 0]
    tc_vals = [round(0.005 * i, 4) for i in range(-5, 11)]
    tr_vals = [20.0, 25.0, 30.0, 35.0, 40.0]

    best2 = []
    total2 = len(hd_vals) * len(r_vals) * len(hdg_vals) * len(tc_vals) * len(tr_vals)
    print(f"Searching {total2} combinations...")

    for hd in hd_vals:
        if hd <= 0:
            continue
        for r in r_vals:
            if r <= 0:
                continue
            mdg = r * hd
            for hdg in hdg_vals:
                for tc in tc_vals:
                    for tr in tr_vals:
                        exact, err = evaluate(test_cases, hd, mdg, hdg, tc, tr)
                        best2.append((exact, -err, hd, r, mdg, hdg, tc, tr))

    best2.sort(reverse=True)
    print(f"\nTop 20:")
    print(f"{'exact':>6} {'err':>8} {'hd':>6} {'r':>8} {'mdg':>8} {'hdg':>6} {'tc':>7} {'tr':>5}")
    for exact, neg_err, hd, r, mdg, hdg, tc, tr in best2[:20]:
        print(f"{exact:>6}/100  {-neg_err:>8.0f}  {hd:>6.2f}  {r:>8.4f}  {mdg:>8.5f}  {hdg:>6.3f}  {tc:>7.4f}  {tr:>5.1f}")

    best_exact, neg_err, best_hd, best_r, best_mdg, best_hdg, best_tc, best_tr = best2[0]
    print(f"\nBest: hd={best_hd}, mdg={best_mdg}, hdg={best_hdg}, tc={best_tc}, tr={best_tr}")
    print(f"Score: {best_exact}/100, err={-neg_err:.0f}")


if __name__ == "__main__":
    main()
