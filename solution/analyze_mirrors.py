#!/usr/bin/env python3
"""
Analyze mirror strategy pairs in historical races to deduce the correct formula.
For mirror pairs (same compounds, same stint lengths, different order):
  - tire-age formula gives IDENTICAL times → lower grid should always win
  - But data shows sometimes higher grid wins

Find what the actual pattern is.
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent

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


def analyze_race(race):
    cfg = race["race_config"]
    T = cfg["total_laps"]
    temp = cfg["track_temp"]
    strats = race["strategies"]
    expected = race["finishing_positions"]

    # Build driver info
    driver_info = {}
    for pos_key, strategy in strats.items():
        grid_pos = int(pos_key[3:])
        driver_id = strategy["driver_id"]
        stints = get_stints(strategy, T)
        stint_sig = tuple((c, n) for c, _, n in stints)
        pit_laps = [s["lap"] for s in sorted(strategy.get("pit_stops", []), key=lambda p: p["lap"])]
        driver_info[driver_id] = {
            "grid": grid_pos,
            "stints": stints,
            "sig": stint_sig,
            "n_stops": len(strategy.get("pit_stops", [])),
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
            compounds1 = sorted(sig1, key=lambda x: x[0])
            compounds2 = sorted(sig2, key=lambda x: x[0])
            if compounds1 == compounds2:
                pos1 = expected.index(d1)
                pos2 = expected.index(d2)
                winner = d1 if pos1 < pos2 else d2
                winner_info = info1 if winner == d1 else info2
                loser_info = info2 if winner == d1 else info1
                mirrors.append({
                    "d1": d1, "info1": info1, "pos1": pos1,
                    "d2": d2, "info2": info2, "pos2": pos2,
                    "winner": winner, "winner_info": winner_info, "loser_info": loser_info,
                    "temp": temp, "T": T,
                    "compounds": sig1
                })
    return mirrors


def main():
    # Load 5 race files and analyze mirror pairs
    all_mirrors = []
    races_analyzed = 0

    for file_idx in range(5):
        fname = ROOT / "data" / "historical_races" / f"races_{file_idx*1000:05d}-{file_idx*1000+999:05d}.json"
        with open(fname) as f:
            races = json.load(f)

        for race in races[:200]:  # First 200 from each file = 1000 races
            mirrors = analyze_race(race)
            all_mirrors.extend(mirrors)
            races_analyzed += 1

    print(f"Analyzed {races_analyzed} races, found {len(all_mirrors)} mirror pairs")
    print()

    # Focus on single-stop MEDIUM/HARD mirrors
    mh_mirrors = [m for m in all_mirrors
                  if len(m["compounds"]) == 2 and
                  {m["compounds"][0][0], m["compounds"][1][0]} == {"MEDIUM", "HARD"}]
    print(f"MEDIUM/HARD single-stop mirrors: {len(mh_mirrors)}")

    # For each mirror pair, compute:
    # - winner's compound order (HARD-first or MEDIUM-first)
    # - stint lengths
    # - pit lap
    # - who has higher grid
    # - temperature, T

    hard_first_wins = 0
    medium_first_wins = 0
    anomalies = []  # cases where lower grid loses

    for m in mh_mirrors:
        w = m["winner_info"]
        l = m["loser_info"]
        w_first_cmpd = w["sig"][0][0]
        l_first_cmpd = l["sig"][0][0]

        if w_first_cmpd == "HARD":
            hard_first_wins += 1
        else:
            medium_first_wins += 1

        lower_grid_wins = w["grid"] < l["grid"]
        if not lower_grid_wins:
            # Compute the stint sums
            stint1_len_w = w["sig"][0][1]
            stint1_len_l = l["sig"][0][1]
            anomalies.append({
                "temp": m["temp"], "T": m["T"],
                "winner_grid": w["grid"], "loser_grid": l["grid"],
                "winner_first": w_first_cmpd, "loser_first": l_first_cmpd,
                "winner_sig": w["sig"], "loser_sig": l["sig"],
                "winner_pit": w["pit_laps"], "loser_pit": l["pit_laps"],
            })

    print(f"HARD-first wins: {hard_first_wins}")
    print(f"MEDIUM-first wins: {medium_first_wins}")
    print(f"Lower grid loses (anomalies): {len(anomalies)}")
    print()

    # Analyze anomalies: what's common between them?
    if anomalies:
        print("Analyzing anomalies (lower grid loses):")
        # In anomalies, the WINNER has higher grid.
        # What is the relationship between winner and loser?
        h_first_wins = sum(1 for a in anomalies if a["winner_first"] == "HARD")
        m_first_wins = sum(1 for a in anomalies if a["winner_first"] == "MEDIUM")
        print(f"  HARD-first wins among anomalies: {h_first_wins}")
        print(f"  MEDIUM-first wins among anomalies: {m_first_wins}")
        print()

        # For each anomaly, compute:
        # MEDIUM stint is run on different lap ranges for winner vs loser
        # With abs-lap formula (hdg=0): MEDIUM-first is always better
        # With tire-age formula: always tied, so lower grid wins
        print("First 20 anomalies:")
        for a in anomalies[:20]:
            w_first = a["winner_first"]
            l_first = a["loser_first"]
            w_sig = a["winner_sig"]
            l_sig = a["loser_sig"]
            T = a["T"]

            # Compute MEDIUM stint range for each driver with original pit convention
            # winner: compound1 for sig[0][1] laps, then compound2 for sig[1][1] laps
            w_start1 = 0
            w_n1 = w_sig[0][1]
            w_start2 = w_n1
            w_n2 = w_sig[1][1]

            l_start1 = 0
            l_n1 = l_sig[0][1]
            l_start2 = l_n1
            l_n2 = l_sig[1][1]

            # Which stint is MEDIUM for each?
            if w_first == "MEDIUM":
                w_med_range = (1, w_n1)  # laps 1 to n1
                l_med_range = (w_n1+1, T)  # laps n1+1 to T (but n1 is winner's so...)
                # Actually for loser (HARD-first):
                l_hard_range = (1, l_n1)
                l_med_range = (l_n1+1, T)
            else:
                w_hard_range = (1, w_n1)
                w_med_range = (w_n1+1, T)
                l_med_range = (1, l_n1)

            # MEDIUM sum with abs-lap
            def sum_range(a, b):
                return (a+b)*(b-a+1)//2

            if w_first == "MEDIUM":
                w_med_sum = sum_range(1, w_n1)
                l_med_sum = sum_range(l_n1+1, T)
            else:
                w_med_sum = sum_range(w_n1+1, T)
                l_med_sum = sum_range(1, l_n1)

            print(f"  T={T}, temp={a['temp']}, w_grid={a['winner_grid']}, l_grid={a['loser_grid']}")
            print(f"    winner: {w_sig}, pit={a['winner_pit']}, MEDIUM sum={w_med_sum if w_first=='MEDIUM' else 'HARD first'}")
            print(f"    loser:  {l_sig}, pit={a['loser_pit']}, MEDIUM sum={l_med_sum}")
            print(f"    abs-lap winner? {'YES' if w_med_sum < l_med_sum else 'NO (tire-age ties, grid should win)'}")

    # Now look at tire-age formula analysis:
    # For every anomaly where tire-age gives a tie and lower-grid loses,
    # can we find a formula that explains BOTH why tire-age ties exist and
    # why the higher-grid driver wins?
    print()
    print("HARD/SOFT mirror pairs analysis:")
    hs_mirrors = [m for m in all_mirrors
                  if len(m["compounds"]) == 2 and
                  {m["compounds"][0][0], m["compounds"][1][0]} == {"HARD", "SOFT"}]
    print(f"Total HARD/SOFT mirrors: {len(hs_mirrors)}")

    hs_anomalies = [m for m in hs_mirrors if m["winner_info"]["grid"] > m["loser_info"]["grid"]]
    print(f"HARD/SOFT anomalies: {len(hs_anomalies)}")

    print()
    print("MEDIUM/SOFT mirror pairs analysis:")
    ms_mirrors = [m for m in all_mirrors
                  if len(m["compounds"]) == 2 and
                  {m["compounds"][0][0], m["compounds"][1][0]} == {"MEDIUM", "SOFT"}]
    print(f"Total MEDIUM/SOFT mirrors: {len(ms_mirrors)}")

    ms_anomalies = [m for m in ms_mirrors if m["winner_info"]["grid"] > m["loser_info"]["grid"]]
    print(f"MEDIUM/SOFT anomalies: {len(ms_anomalies)}")

    # Key statistical question: for MEDIUM/HARD mirror pairs,
    # does the abs-lap formula ALWAYS predict the winner?
    print()
    print("=== Does abs-lap (hdg=0) formula predict anomaly winners? ===")
    abs_lap_correct = 0
    abs_lap_wrong = 0
    for a in anomalies:
        w_first = a["winner_first"]
        l_first = a["loser_first"]
        w_sig = a["winner_sig"]
        l_sig = a["loser_sig"]
        T = a["T"]

        # With abs-lap and hdg=0:
        # MEDIUM-first driver has MEDIUM on laps 1..n1 (lower sum)
        # HARD-first driver has MEDIUM on laps n1+1..T (higher sum)
        # MEDIUM-first ALWAYS wins with abs-lap and hdg=0
        abs_lap_predicts_medium_first = True  # abs-lap predicts MEDIUM-first wins

        if (w_first == "MEDIUM") == abs_lap_predicts_medium_first:
            abs_lap_correct += 1
        else:
            abs_lap_wrong += 1

    print(f"Abs-lap predicts correctly: {abs_lap_correct}/{len(anomalies)}")
    print(f"Abs-lap predicts wrong: {abs_lap_wrong}/{len(anomalies)}")


if __name__ == "__main__":
    main()
