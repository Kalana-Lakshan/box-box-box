#!/usr/bin/env python3
"""Compare tire-age vs lap-number formula accuracy, and find mirror strategy anomalies."""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
RATIO_SD_HD = -1.25
RATIO_SDG_MDG = 4.75
HDG_VALUE = 0.0


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
        test_cases.append((name, inp, out["finishing_positions"]))
    return test_cases


def get_stints(strategy, T):
    stops = sorted(strategy.get("pit_stops", []), key=lambda p: p["lap"])
    stints = []
    current_compound = strategy["starting_tire"]
    prev_lap = 0
    for stop in stops:
        lap = stop["lap"]
        stints.append((current_compound, prev_lap, lap - prev_lap))
        current_compound = stop["to_tire"]
        prev_lap = lap
    stints.append((current_compound, prev_lap, T - prev_lap))
    return stints


def compute_time_tireage(strategy, cfg, hd, mdg, tc, tr):
    T = cfg["total_laps"]
    base = cfg["base_lap_time"]
    pit = cfg["pit_lane_time"]
    temp = cfg["track_temp"]
    tf = 1.0 + tc * (temp - tr)
    sd = RATIO_SD_HD * hd
    sdg = RATIO_SDG_MDG * mdg
    hdg = HDG_VALUE
    deltas = {"SOFT": sd, "MEDIUM": 0.0, "HARD": hd}
    degs = {"SOFT": sdg, "MEDIUM": mdg, "HARD": hdg}
    stints = get_stints(strategy, T)
    total_time = T * base + len(strategy.get("pit_stops", [])) * pit
    for compound, start_lap, n in stints:
        total_time += n * deltas[compound]
        total_time += tf * degs[compound] * n * (n + 1) / 2
    return total_time


def compute_time_laplap(strategy, cfg, hd, mdg, tc, tr):
    T = cfg["total_laps"]
    base = cfg["base_lap_time"]
    pit = cfg["pit_lane_time"]
    temp = cfg["track_temp"]
    tf = 1.0 + tc * (temp - tr)
    sd = RATIO_SD_HD * hd
    sdg = RATIO_SDG_MDG * mdg
    hdg = HDG_VALUE
    deltas = {"SOFT": sd, "MEDIUM": 0.0, "HARD": hd}
    degs = {"SOFT": sdg, "MEDIUM": mdg, "HARD": hdg}
    stints = get_stints(strategy, T)
    total_time = T * base + len(strategy.get("pit_stops", [])) * pit
    for compound, start_lap, n in stints:
        total_time += n * deltas[compound]
        # absolute race lap: start_lap+1 .. start_lap+n
        lap_sum = n * (2 * start_lap + n + 1) / 2
        total_time += tf * degs[compound] * lap_sum
    return total_time


def simulate(test_input, time_fn, hd, mdg, tc, tr):
    cfg = test_input["race_config"]
    strats = test_input["strategies"]
    results = []
    for pos_key, strategy in strats.items():
        grid_pos = int(pos_key[3:])
        t = time_fn(strategy, cfg, hd, mdg, tc, tr)
        results.append((t, grid_pos, strategy["driver_id"]))
    results.sort(key=lambda x: (x[0], x[1]))
    return [r[2] for r in results]


def find_mirror_pairs(test_input, expected):
    """Find drivers with exactly mirrored strategies (same compounds, same stint lengths, different order)."""
    cfg = test_input["race_config"]
    T = cfg["total_laps"]
    strats = test_input["strategies"]

    # Build stint signature for each driver
    driver_info = {}
    for pos_key, strategy in strats.items():
        grid_pos = int(pos_key[3:])
        driver_id = strategy["driver_id"]
        stints = get_stints(strategy, T)
        stint_sig = tuple((c, n) for c, _, n in stints)
        num_stops = len(strategy.get("pit_stops", []))
        pit_laps = [s["lap"] for s in sorted(strategy.get("pit_stops", []), key=lambda p: p["lap"])]
        driver_info[driver_id] = {
            "grid": grid_pos,
            "stints": stints,
            "sig": stint_sig,
            "n_stops": num_stops,
            "pit_laps": pit_laps,
        }

    drivers = list(driver_info.keys())
    mirrors = []
    for i, d1 in enumerate(drivers):
        for d2 in drivers[i + 1:]:
            info1 = driver_info[d1]
            info2 = driver_info[d2]
            if info1["n_stops"] != info2["n_stops"]:
                continue
            sig1 = info1["sig"]
            sig2 = info2["sig"]
            if sig1 == sig2:
                continue  # identical, not mirror
            # Check if they have same compound counts and same stint lengths (just different order)
            compounds1 = sorted(sig1, key=lambda x: x[0])
            compounds2 = sorted(sig2, key=lambda x: x[0])
            if compounds1 == compounds2:
                # Same compounds+lengths, different ordering - true mirror
                pos1 = expected.index(d1)
                pos2 = expected.index(d2)
                mirrors.append({
                    "d1": d1, "grid1": info1["grid"], "pos1": pos1,
                    "sig1": sig1, "pit_laps1": info1["pit_laps"],
                    "d2": d2, "grid2": info2["grid"], "pos2": pos2,
                    "sig2": sig2, "pit_laps2": info2["pit_laps"],
                })
    return mirrors


def main():
    hd = 4.44
    mdg = 0.180264
    tc = -0.005
    tr = 40.0

    test_cases = load_test_cases()
    print(f"Loaded {len(test_cases)} test cases")
    print()

    ta_exact = 0
    lap_exact = 0
    ta_err = 0
    lap_err = 0

    # Also do a grid search with lap-number formula
    print("Testing calibrated params with both formulas...")
    for name, inp, expected in test_cases:
        pred_ta = simulate(inp, compute_time_tireage, hd, mdg, tc, tr)
        pred_lap = simulate(inp, compute_time_laplap, hd, mdg, tc, tr)
        if pred_ta == expected:
            ta_exact += 1
        else:
            for pp, ep in enumerate(expected):
                ap = pred_ta.index(ep)
                ta_err += abs(pp - ap)
        if pred_lap == expected:
            lap_exact += 1
        else:
            for pp, ep in enumerate(expected):
                ap = pred_lap.index(ep)
                lap_err += abs(pp - ap)

    print(f"Tire-age  formula: {ta_exact}/100 exact, total pos err = {ta_err}")
    print(f"Lap-number formula: {lap_exact}/100 exact, total pos err = {lap_err}")
    print()

    # Now find all mirror pairs across all test cases
    print("=== Mirror strategy pairs analysis ===")
    mirror_stats = {"grid_wins": 0, "grid_loses": 0, "early_pit_wins": 0, "early_pit_loses": 0}
    anomalies = []
    for name, inp, expected in test_cases:
        mirrors = find_mirror_pairs(inp, expected)
        for m in mirrors:
            d1_wins = m["pos1"] < m["pos2"]
            # Which driver has lower grid pos?
            lower_grid_wins = (m["grid1"] < m["grid2"]) == d1_wins
            # Which driver pits earlier?
            if m["pit_laps1"] and m["pit_laps2"]:
                earlier_pit_wins = (m["pit_laps1"][0] < m["pit_laps2"][0]) == d1_wins
            else:
                earlier_pit_wins = None

            if lower_grid_wins:
                mirror_stats["grid_wins"] += 1
            else:
                mirror_stats["grid_loses"] += 1
                # Anomaly! Lower grid loses
                anomalies.append((name, m))

            if earlier_pit_wins is True:
                mirror_stats["early_pit_wins"] += 1
            elif earlier_pit_wins is False:
                mirror_stats["early_pit_loses"] += 1

    print(f"Total mirror pairs: {mirror_stats['grid_wins'] + mirror_stats['grid_loses']}")
    print(f"Lower grid wins: {mirror_stats['grid_wins']}")
    print(f"Lower grid LOSES (anomalies!): {mirror_stats['grid_loses']}")
    print(f"Earlier pit wins: {mirror_stats['early_pit_wins']}")
    print(f"Earlier pit loses: {mirror_stats['early_pit_loses']}")
    print()

    if anomalies:
        print(f"Anomalous mirror pairs ({len(anomalies)}):")
        for test_name, m in anomalies[:20]:
            print(f"  {test_name}: {m['d1']}(grid={m['grid1']},pit={m['pit_laps1']}) vs "
                  f"{m['d2']}(grid={m['grid2']},pit={m['pit_laps2']})")
            print(f"    finish: {m['d1']}={m['pos1']+1}, {m['d2']}={m['pos2']+1}")
            print(f"    stints: {m['sig1']} vs {m['sig2']}")

    # Now do grid search for lap-number formula params
    print()
    print("=== Grid search for lap-number formula ===")
    hd_values = [round(0.1 * i, 2) for i in range(1, 51)]
    r_values = [round(0.001 * i, 4) for i in range(1, 51)]
    best_results = []
    for hd_v in hd_values:
        for r in r_values:
            mdg_v = r * hd_v
            exact = 0
            err = 0
            for _, inp, expected in test_cases:
                pred = simulate(inp, compute_time_laplap, hd_v, mdg_v, 0.0, 25.0)
                if pred == expected:
                    exact += 1
                else:
                    for pp, ep in enumerate(expected):
                        ap = pred.index(ep)
                        err += abs(pp - ap)
            best_results.append((exact, -err, hd_v, r, mdg_v))
    best_results.sort(reverse=True)
    print(f"Top 10 lap-number params (no temp):")
    print(f"{'exact':>6} {'err':>8} {'hd':>6} {'r':>8} {'mdg':>8}")
    for exact, neg_err, hd_v, r, mdg_v in best_results[:10]:
        print(f"{exact:>6}/100  {-neg_err:>8.0f}  {hd_v:>6.2f}  {r:>8.4f}  {mdg_v:>8.5f}")


if __name__ == "__main__":
    main()
