import os
import csv
import json
import datetime
import subprocess
import math
from collections import defaultdict

REPO_DIR = os.path.expanduser("~/Skydiving-Skytrack")
IMPORTS_DIR = os.path.join(REPO_DIR, "imports")
DATA_DIR = os.path.join(REPO_DIR, "data")
RUNS_DIR = os.path.join(DATA_DIR, "runs")
INDEX_PATH = os.path.join(DATA_DIR, "index.json")
CONFIG_PATH = os.path.join(REPO_DIR, "aircraft.json")

def load_fleet():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r") as f:
        return {ac["reg"]: ac for ac in json.load(f)}

def circular_mean_heading(angles_deg):
    x = sum(math.cos(math.radians(a)) for a in angles_deg)
    y = sum(math.sin(math.radians(a)) for a in angles_deg)
    return round(math.degrees(math.atan2(y, x)) % 360)

def parse_fr24_csv(filepath):
    points = []
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = int(row.get("Timestamp") or 0)
                if "Position" in row and row["Position"]:
                    lat_str, lon_str = row["Position"].split(",")
                    lat, lon = float(lat_str.strip()), float(lon_str.strip())
                else:
                    lat = float(row.get("Latitude", 0))
                    lon = float(row.get("Longitude", 0))

                alt_ft = float(row.get("Altitude", 0))
                speed_kt = float(row.get("Speed", 0))
                track = float(row.get("Direction", 0))
                alt_m = int(alt_ft * 0.3048)

                points.append({
                    "time": ts,
                    "lat": lat,
                    "lon": lon,
                    "track": track,
                    "alt_m": alt_m,
                    "alt_ft": alt_ft,
                    "speed_kt": speed_kt
                })
            except Exception:
                continue
    return points

def extract_jump_runs_by_decollo(points):
    if len(points) < 15:
        return []

    # 1. Deduplica e ordina per timestamp
    points.sort(key=lambda x: x["time"])
    dedup = [points[0]]
    for p in points[1:]:
        if p["time"] != dedup[-1]["time"]:
            dedup.append(p)
    points = dedup

    n = len(points)
    if n < 15:
        return []

    # 2. Calcolo variometro su finestra mobile di 5 campioni (10-12s)
    window = 5
    for i in range(n):
        j = max(0, i - window)
        dt = points[i]["time"] - points[j]["time"]
        if dt > 0:
            points[i]["v_rate_smooth"] = ((points[i]["alt_ft"] - points[j]["alt_ft"]) / dt) * 60.0
        else:
            points[i]["v_rate_smooth"] = 0.0

    # 3. Individua l'inizio delle vere picchiate (discesa ripida sostenuta <= -2000 fpm)
    dives = []
    for i, p in enumerate(points):
        if p["v_rate_smooth"] <= -2000:
            if not dives or (p["time"] - points[dives[-1]]["time"] > 600):
                dives.append(i)

    # 4. Per ogni picchiata, raccoglie l'intera passata di lancio (fino a 3 minuti prima)
    runs = []
    for d_idx in dives:
        dive_time = points[d_idx]["time"]
        candidates = [p for p in points if dive_time - 180 <= p["time"] <= dive_time]
        if not candidates:
            continue
        max_alt = max(p["alt_m"] for p in candidates)

        run_seg = []
        for p in reversed(candidates):
            # Parametri di run-in: quota lancio >= 2800m, dislivello massimo tollerato 350m, velocità 30-105 kt
            if p["alt_m"] >= 2800 and (max_alt - p["alt_m"] <= 350) and (30 <= p["speed_kt"] <= 105):
                if p.get("v_rate_smooth", 0) <= 800:
                    run_seg.insert(0, p)
                else:
                    if len(run_seg) >= 5:
                        break
            else:
                if len(run_seg) >= 5:
                    break

        if len(run_seg) >= 5:
            dur = run_seg[-1]["time"] - run_seg[0]["time"]
            if dur >= 20:
                runs.append(run_seg)

    # 5. Rimuove sovrapposizioni temporali
    unique_runs = []
    for r in runs:
        if not unique_runs:
            unique_runs.append(r)
        else:
            if r[0]["time"] > unique_runs[-1][-1]["time"] + 30:
                unique_runs.append(r)

    # 6. Raggruppa per ciclo di decollo (> 15 minuti di stacco)
    decolli = []
    curr = []
    for r in unique_runs:
        if not curr:
            curr.append(r)
        else:
            if r[0]["time"] - curr[-1][-1]["time"] > 900:
                decolli.append(curr)
                curr = [r]
            else:
                curr.append(r)
    if curr:
        decolli.append(curr)

    return decolli

def process_all_imports():
    fleet = load_fleet()
    if not os.path.exists(IMPORTS_DIR):
        print("Cartella imports non trovata.")
        return

    csv_files = [f for f in os.listdir(IMPORTS_DIR) if f.lower().endswith(".csv")]
    if not csv_files:
        print("Nessun CSV trovato in imports/")
        return

    print(f"📂 Trovati {len(csv_files)} file CSV. Inizio aggregazione...")

    points_by_ac_date = defaultdict(list)

    for fname in csv_files:
        fpath = os.path.join(IMPORTS_DIR, fname)
        matched_reg = None
        for reg in fleet.keys():
            if reg.replace("-", "").upper() in fname.upper() or reg.upper() in fname.upper():
                matched_reg = reg
                break

        if not matched_reg:
            print(f"⚠️ Ignorato file non associabile alla flotta: {fname}")
            continue

        pts = parse_fr24_csv(fpath)
        for p in pts:
            dt = datetime.datetime.fromtimestamp(p["time"], tz=datetime.timezone.utc)
            d_str = dt.strftime("%Y-%m-%d")
            points_by_ac_date[(matched_reg, d_str)].append(p)

    with open(INDEX_PATH, "r") as f:
        master_index = json.load(f)

    total_runs_imported = 0

    for (reg, d_str), raw_points in sorted(points_by_ac_date.items()):
        decolli = extract_jump_runs_by_decollo(raw_points)
        print(f"\n🗓️  {reg} - Data {d_str}: estratti {len(decolli)} decolli completi.")

        ac_dir = os.path.join(RUNS_DIR, reg)
        os.makedirs(ac_dir, exist_ok=True)

        for d_idx, runs_in_dec in enumerate(decolli, 1):
            for r_idx, run_segment in enumerate(runs_in_dec, 1):
                duration = int(run_segment[-1]["time"] - run_segment[0]["time"])
                avg_speed = round(sum(p["speed_kt"] for p in run_segment) / len(run_segment), 1)
                avg_track = circular_mean_heading([p["track"] for p in run_segment])
                exit_alt = run_segment[0]["alt_m"]

                speed_mps = avg_speed * 0.514444
                sep_300m = round(300.0 / speed_mps, 1) if speed_mps > 0 else 0

                dt = datetime.datetime.fromtimestamp(run_segment[0]["time"], tz=datetime.timezone.utc)
                time_str = dt.strftime("%H:%M")

                title = f"Decollo #{d_idx}" if len(runs_in_dec) == 1 else f"Decollo #{d_idx} (Lancio {r_idx})"
                run_filename = f"{d_str}_dec_{d_idx:02d}_{r_idx:02d}.json"
                run_filepath = os.path.join(ac_dir, run_filename)

                run_data = {
                    "reg": reg,
                    "dropzone": fleet[reg]["name"],
                    "date": d_str,
                    "time": time_str,
                    "stats": {
                        "altitude_m": exit_alt,
                        "heading_deg": avg_track,
                        "ground_speed_kt": avg_speed,
                        "separation_sec": sep_300m,
                        "duration_sec": duration
                    },
                    "points": [{"lat": p["lat"], "lon": p["lon"]} for p in run_segment]
                }

                with open(run_filepath, "w") as rf:
                    json.dump(run_data, rf, indent=2)

                for ac_entry in master_index["aircrafts"]:
                    if ac_entry["reg"] == reg:
                        ac_entry["runs"] = [x for x in ac_entry["runs"] if x["file"] != f"{reg}/{run_filename}"]
                        ac_entry["runs"].append({
                            "file": f"{reg}/{run_filename}",
                            "date": d_str,
                            "time": time_str,
                            "title": title,
                            "duration_sec": duration,
                            "heading_deg": avg_track,
                            "speed_kt": avg_speed
                        })
                        ac_entry["runs"].sort(key=lambda x: f"{x['date']} {x['time']}", reverse=True)
                        break

                total_runs_imported += 1
                dur_m, dur_s = divmod(duration, 60)
                print(f"   ▶ {title} [{time_str} UTC] Durata: {dur_m}m {dur_s:02d}s ({duration}s) | Quota: {exit_alt}m | Asse: {avg_track}° | GS: {avg_speed}kt | Sep: {sep_300m}s")

    if total_runs_imported > 0:
        master_index["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(INDEX_PATH, "w") as f:
            json.dump(master_index, f, indent=2)

        print("\n☁️  Sincronizzazione su GitHub in corso...")
        subprocess.run(["git", "-C", REPO_DIR, "add", "."], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "commit", "-m", f"Aggiornamento storico: {total_runs_imported} lanci completi importati"], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "push"], check=True)
        print("✅ Storico aggiornato con tracce complete su GitHub Pages!")
    else:
        print("Nessun nuovo lancio importato.")

if __name__ == "__main__":
    process_all_imports()
