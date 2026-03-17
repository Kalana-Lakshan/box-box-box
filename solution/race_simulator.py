#!/usr/bin/env python3
"""
F1 Race Simulator
Reads JSON from stdin, outputs finishing positions.
"""
import json
import sys

# Calibrated parameters
HD = 4.05       # HARD compound delta (seconds per lap slower than MEDIUM)
SD = -5.0625    # SOFT compound delta (seconds per lap faster than MEDIUM)
MDG = 0.164     # MEDIUM degradation rate (seconds per lap per lap-age)
SDG = 0.779     # SOFT degradation rate (4.75 * MDG)
HDG = 0.0       # HARD degradation rate
TC = 0.009      # Temperature coefficient
TR = 27.0       # Reference temperature


def compute_race_time(strategy, cfg):
    T = cfg["total_laps"]
    base = cfg["base_lap_time"]
    pit = cfg["pit_lane_time"]
    temp = cfg["track_temp"]
    tf = 1.0 + TC * (temp - TR)

    deltas = {"SOFT": SD, "MEDIUM": 0.0, "HARD": HD}
    degs = {"SOFT": SDG, "MEDIUM": MDG, "HARD": HDG}

    # Convention B: pit_lap is last lap on old tires, pit happens at end of that lap
    stops = {s["lap"]: s["to_tire"] for s in strategy.get("pit_stops", [])}

    total_time = 0.0
    tire_age = 0
    compound = strategy["starting_tire"]

    for lap in range(1, T + 1):
        tire_age += 1
        total_time += base + deltas[compound] + degs[compound] * tire_age * tf
        if lap in stops:
            total_time += pit
            compound = stops[lap]
            tire_age = 0

    return total_time


def simulate(race_data):
    cfg = race_data["race_config"]
    strategies = race_data["strategies"]

    results = []
    for pos_key, strategy in strategies.items():
        grid_pos = int(pos_key[3:])  # "pos15" -> 15
        t = compute_race_time(strategy, cfg)
        results.append((t, grid_pos, strategy["driver_id"]))

    # Sort by time, break ties by grid position
    results.sort(key=lambda x: (x[0], x[1]))
    return [r[2] for r in results]


def main():
    data = json.load(sys.stdin)
    finishing_positions = simulate(data)
    output = {
        "race_id": data["race_config"]["race_id"],
        "finishing_positions": finishing_positions
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
