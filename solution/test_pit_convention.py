#!/usr/bin/env python3
"""
Test different pit timing conventions to see which matches the test data better.

Convention A: pit_lap = lap when driver STARTS on new tires (first new tire lap)
  - laps 1..pit_lap-1 on old tires, laps pit_lap..T on new tires

Convention B: pit_lap = lap when driver LAST drives on old tires
  - laps 1..pit_lap on old tires, laps pit_lap+1..T on new tires

Also test where pit_time is added: before or after the compound switch.
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Best params from calibrate.py (closed-form, tire-age formula)
HD = 4.44
MDG = 0.180264
HDG = 0.0
TC = -0.005
TR = 40.0
SD = -1.25 * HD
SDG = 4.75 * MDG


def simulate_convention(test_input, hd, mdg, hdg, tc, tr, convention, pit_time_pos):
    """
    convention: 'A' (pit_lap = first new lap) or 'B' (pit_lap = last old lap)
    pit_time_pos: 'before' (before new compound) or 'after' (after old compound)
    """
    cfg = test_input["race_config"]
    T = cfg["total_laps"]
    base = cfg["base_lap_time"]
    pit = cfg["pit_lane_time"]
    temp = cfg["track_temp"]
    tf = 1.0 + tc * (temp - tr)

    sd = -1.25 * hd
    sdg = 4.75 * mdg
    deltas = {"SOFT": sd, "MEDIUM": 0.0, "HARD": hd}
    degs = {"SOFT": sdg, "MEDIUM": mdg, "HARD": hdg}

    strats = test_input["strategies"]
    results = []

    for pos_key, strategy in strats.items():
        grid_pos = int(pos_key[3:])
        driver_id = strategy["driver_id"]
        stops_raw = {s["lap"]: s["to_tire"] for s in strategy.get("pit_stops", [])}

        compound = strategy["starting_tire"]
        tire_age = 0
        total_time = 0.0

        for lap in range(1, T + 1):
            if convention == 'A':
                # pit_lap = first lap on new tires: switch at start of pit_lap
                if lap in stops_raw:
                    if pit_time_pos == 'before':
                        total_time += pit
                    compound = stops_raw[lap]
                    tire_age = 0
                    if pit_time_pos == 'after':
                        total_time += pit
            elif convention == 'B':
                # pit_lap = last lap on old tires: switch at start of pit_lap+1
                if lap in {k + 1: v for k, v in stops_raw.items()}:
                    new_c = stops_raw[lap - 1]
                    if pit_time_pos == 'before':
                        total_time += pit
                    compound = new_c
                    tire_age = 0
                    if pit_time_pos == 'after':
                        total_time += pit

            tire_age += 1
            total_time += base + deltas[compound] + degs[compound] * tire_age * tf

        results.append((total_time, grid_pos, driver_id))

    results.sort(key=lambda x: (x[0], x[1]))
    return [r[2] for r in results]


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


def evaluate_all(test_cases, hd, mdg, hdg, tc, tr):
    results = {}
    for conv in ['A', 'B']:
        for pos in ['before', 'after']:
            key = f"{conv}_{pos}"
            exact = 0
            err = 0
            for name, inp, expected in test_cases:
                pred = simulate_convention(inp, hd, mdg, hdg, tc, tr, conv, pos)
                if pred == expected:
                    exact += 1
                else:
                    for pp, ep in enumerate(expected):
                        ap = pred.index(ep)
                        err += abs(pp - ap)
            results[key] = (exact, err)
    return results


def main():
    test_cases = load_test_cases()
    print(f"Loaded {len(test_cases)} test cases")
    print()

    # Test with calibrated params
    print("=== Testing pit conventions with calibrated params ===")
    print(f"hd={HD}, mdg={MDG}, hdg={HDG}, tc={TC}, tr={TR}")
    results = evaluate_all(test_cases, HD, MDG, HDG, TC, TR)
    for key, (exact, err) in sorted(results.items()):
        print(f"  Convention {key}: {exact}/100 exact, err={err}")
    print()

    # Also verify specific test cases
    print("=== Checking test_009 D015 vs D018 ===")
    test_009_inp = None
    for name, inp, exp in test_cases:
        if name == "test_009":
            test_009_inp = inp
            test_009_exp = exp
            break

    if test_009_inp:
        cfg = test_009_inp["race_config"]
        d015_strat = test_009_inp["strategies"]["pos15"]
        d018_strat = test_009_inp["strategies"]["pos18"]

        for conv in ['A', 'B']:
            for pos in ['before', 'after']:
                # Compute times for D015 and D018
                t_d015 = 0.0; t_d018 = 0.0
                T = cfg["total_laps"]
                base = cfg["base_lap_time"]
                pit = cfg["pit_lane_time"]
                temp = cfg["track_temp"]
                tf = 1.0 + TC * (temp - TR)
                deltas = {"SOFT": -1.25*HD, "MEDIUM": 0.0, "HARD": HD}
                degs = {"SOFT": 4.75*MDG, "MEDIUM": MDG, "HARD": HDG}

                for strategy, label in [(d015_strat, 'D015'), (d018_strat, 'D018')]:
                    stops_raw = {s["lap"]: s["to_tire"] for s in strategy.get("pit_stops", [])}
                    compound = strategy["starting_tire"]
                    tire_age = 0
                    total = 0.0
                    for lap in range(1, T + 1):
                        if conv == 'A':
                            if lap in stops_raw:
                                if pos == 'before':
                                    total += pit
                                compound = stops_raw[lap]
                                tire_age = 0
                                if pos == 'after':
                                    total += pit
                        elif conv == 'B':
                            next_stops = {k + 1: v for k, v in stops_raw.items()}
                            if lap in next_stops:
                                if pos == 'before':
                                    total += pit
                                compound = next_stops[lap]
                                tire_age = 0
                                if pos == 'after':
                                    total += pit
                        tire_age += 1
                        total += base + deltas[compound] + degs[compound] * tire_age * tf
                    if label == 'D015':
                        t_d015 = total
                    else:
                        t_d018 = total

                winner = "D015" if t_d015 < t_d018 else "D018" if t_d018 < t_d015 else "TIE"
                expected_winner = "D018"  # D018 finishes 3rd, D015 finishes 4th
                print(f"  Conv {conv}_{pos}: D015={t_d015:.10f}, D018={t_d018:.10f}, "
                      f"winner={winner}, expected={expected_winner}, "
                      f"diff={abs(t_d015-t_d018):.2e}, {'OK' if winner==expected_winner else 'WRONG'}")

    # Now test with different params including non-zero hdg
    print()
    print("=== Quick search for better params with hdg free ===")
    best = (0, 1e18, None)
    for hd in [3.0, 3.5, 4.0, 4.44, 5.0]:
        for r in [0.035, 0.04, 0.041, 0.042, 0.045, 0.05]:
            mdg = r * hd
            for hdg in [0.0, 0.01, 0.02, 0.03, 0.05]:
                for tc in [-0.005, 0.0, 0.005]:
                    for tr in [35.0, 40.0]:
                        results = evaluate_all(test_cases, hd, mdg, hdg, tc, tr)
                        for key, (exact, err) in results.items():
                            if exact > best[0] or (exact == best[0] and err < best[1]):
                                best = (exact, err, (hd, mdg, hdg, tc, tr, key))
    print(f"Best: {best[0]}/100, err={best[1]}, params={best[2]}")


if __name__ == "__main__":
    main()
