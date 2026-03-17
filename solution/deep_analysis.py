#!/usr/bin/env python3
"""
Deep analysis: find races with BOTH HARD-first and MEDIUM-first mirror pair wins,
and find the actual formula by looking at what distinguishes the races.
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


def find_mirror_pairs(race):
    cfg = race["race_config"]
    T = cfg["total_laps"]
    strats = race["strategies"]
    expected = race["finishing_positions"]

    driver_info = {}
    for pos_key, strategy in strats.items():
        grid_pos = int(pos_key[3:])
        driver_id = strategy["driver_id"]
        stints = get_stints(strategy, T)
        stint_sig = tuple((c, n) for c, _, n in stints)
        driver_info[driver_id] = {"grid": grid_pos, "sig": stint_sig,
                                   "pit_laps": [s["lap"] for s in sorted(strategy.get("pit_stops", []), key=lambda p: p["lap"])]}

    drivers = list(driver_info.keys())
    pairs = []
    for i, d1 in enumerate(drivers):
        for d2 in drivers[i + 1:]:
            info1 = driver_info[d1]
            info2 = driver_info[d2]
            sig1 = info1["sig"]
            sig2 = info2["sig"]
            if sig1 == sig2:
                continue
            compounds1 = sorted(sig1, key=lambda x: x[0])
            compounds2 = sorted(sig2, key=lambda x: x[0])
            if compounds1 == compounds2 and len(sig1) == 2:
                pos1 = expected.index(d1)
                pos2 = expected.index(d2)
                winner = d1 if pos1 < pos2 else d2
                loser = d2 if pos1 < pos2 else d1
                pairs.append({
                    "d1": d1, "d2": d2,
                    "winner": winner, "loser": loser,
                    "winner_info": driver_info[winner],
                    "loser_info": driver_info[loser],
                })
    return pairs


def main():
    print("Loading races to find both HARD-first and MEDIUM-first wins in same race...")

    fname = ROOT / "data" / "historical_races" / "races_00000-00999.json"
    with open(fname) as f:
        races = json.load(f)

    for race in races[:1000]:
        cfg = race["race_config"]
        T = cfg["total_laps"]
        temp = cfg["track_temp"]
        pairs = find_mirror_pairs(race)

        # Focus on HARD/MEDIUM pairs
        mh_pairs = [p for p in pairs
                    if {p["winner_info"]["sig"][0][0], p["winner_info"]["sig"][1][0]} == {"MEDIUM", "HARD"}]

        if len(mh_pairs) < 2:
            continue

        # Check if we have BOTH HARD-first wins and MEDIUM-first wins
        hard_first_wins = [p for p in mh_pairs if p["winner_info"]["sig"][0][0] == "HARD"]
        medium_first_wins = [p for p in mh_pairs if p["winner_info"]["sig"][0][0] == "MEDIUM"]

        if hard_first_wins and medium_first_wins:
            print(f"\n=== RACE WITH BOTH TYPES: T={T}, temp={temp}, track={cfg['track']} ===")
            print(f"HARD-first wins ({len(hard_first_wins)}):")
            for p in hard_first_wins:
                w = p["winner_info"]
                l = p["loser_info"]
                print(f"  winner: {p['winner']}({w['sig']}), grid={w['grid']}, pit={w['pit_laps']}")
                print(f"  loser:  {p['loser']}({l['sig']}), grid={l['grid']}, pit={l['pit_laps']}")
            print(f"MEDIUM-first wins ({len(medium_first_wins)}):")
            for p in medium_first_wins:
                w = p["winner_info"]
                l = p["loser_info"]
                print(f"  winner: {p['winner']}({w['sig']}), grid={w['grid']}, pit={w['pit_laps']}")
                print(f"  loser:  {p['loser']}({l['sig']}), grid={l['grid']}, pit={l['pit_laps']}")
            # Only show first few
            if len([p for p in races[:1000] if find_mirror_pairs(p)]) > 5:
                break

    print("\n\n=== FINDING PAIRS WHERE N1 < N2 AND HARD-FIRST WINS ===")
    for race in races[:500]:
        cfg = race["race_config"]
        T = cfg["total_laps"]
        temp = cfg["track_temp"]
        pairs = find_mirror_pairs(race)
        for p in pairs:
            w = p["winner_info"]
            if w["sig"][0][0] == "HARD":
                n_hard = w["sig"][0][1]
                n_med = w["sig"][1][1]
                if n_hard < n_med:
                    l = p["loser_info"]
                    print(f"T={T}, temp={temp}: HARD({n_hard})→MED({n_med}) wins (grid={w['grid']}) over MED({n_med})→HARD({n_hard}) (grid={l['grid']})")

    print("\n\n=== ALL MEDIUM/HARD PAIRS FROM FIRST 200 RACES ===")
    rows = []
    for race in races[:500]:
        cfg = race["race_config"]
        T = cfg["total_laps"]
        temp = cfg["track_temp"]
        pit = cfg["pit_lane_time"]
        base = cfg["base_lap_time"]
        pairs = find_mirror_pairs(race)
        for p in pairs:
            w = p["winner_info"]
            l = p["loser_info"]
            if {w["sig"][0][0], w["sig"][1][0]} != {"MEDIUM", "HARD"}:
                continue
            if w["sig"][0][0] == "HARD":
                winner_order = "H_first"
                n_hard = w["sig"][0][1]
                n_med = w["sig"][1][1]
            else:
                winner_order = "M_first"
                n_med = w["sig"][0][1]
                n_hard = w["sig"][1][1]
            winner_pit = w["pit_laps"][0]
            loser_pit = l["pit_laps"][0]
            rows.append((T, temp, n_hard, n_med, winner_order, winner_pit, loser_pit, w["grid"], l["grid"]))

    print(f"Total MEDIUM/HARD mirror pairs: {len(rows)}")
    print()

    # Sort by winner_order
    h_first = [(T, temp, n_hard, n_med, wp, lp, wg, lg) for T, temp, n_hard, n_med, wo, wp, lp, wg, lg in rows if wo == "H_first"]
    m_first = [(T, temp, n_hard, n_med, wp, lp, wg, lg) for T, temp, n_hard, n_med, wo, wp, lp, wg, lg in rows if wo == "M_first"]

    print(f"HARD-first wins: {len(h_first)}")
    print(f"MEDIUM-first wins: {len(m_first)}")
    print()

    # For HARD-first wins: what's the range of n_hard vs n_med?
    print("HARD-first wins: n_hard, n_med, winner_pit, loser_pit, T, temp")
    for T, temp, nh, nm, wp, lp, wg, lg in sorted(h_first, key=lambda x: x[2]-x[3])[:20]:
        print(f"  HARD={nh}, MED={nm}, diff={nh-nm}, winner_pit={wp}(H-first), loser_pit={lp}(M-first), T={T}, temp={temp}")

    print()
    print("MEDIUM-first wins: n_hard, n_med, winner_pit, loser_pit, T, temp")
    for T, temp, nh, nm, wp, lp, wg, lg in sorted(m_first, key=lambda x: x[2]-x[3])[:20]:
        print(f"  HARD={nh}, MED={nm}, diff={nh-nm}, winner_pit={wp}(M-first), loser_pit={lp}(H-first), T={T}, temp={temp}")


if __name__ == "__main__":
    main()
