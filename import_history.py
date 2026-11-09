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
FLEET_FILE = os.path.join(REPO_DIR, "fleet.json")
DROPZONES_FILE = os.path.join(REPO_DIR, "dropzones.json")

def load_fleet():
    if not os.path.exists(FLEET_FILE): return {}
    with open(FLEET_FILE, "r") as f: return json.load(f)

def load_dropzones():
    if not os.path.exists(DROPZONES_FILE): return []
    with open(DROPZONES_FILE, "r") as f: return json.load(f)

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0 # Raggio terrestre in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def find_closest_dz(lat, lon, dropzones):
    closest = None
    min_dist = float('inf')
    for dz in dropzones:
        dist = haversine(lat, lon, dz["center_lat"], dz["center_lon"])
        if dist < min_dist:
            min_dist = dist
            closest = dz
    # Assegna alla dropzone se rientra nel raggio operativo di 50 km
    if closest and min_dist <= 50.0:
        return closest
    return None

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
                    "time": ts, "lat": lat, "lon": lon, "track": track,
                    "alt_m": alt_m, "alt_ft": alt_ft, "speed_kt": speed_kt
                })
            except Exception:
                continue
    return points

def extract_jump_runs_by_decollo(points):
    if len(points) < 15: return []

    points.sort(key=lambda x: x["time"])
    dedup = [points[0]]
    for p in points[1:]:
        if p["time"] != dedup[-1]["time"]: dedup.append(p)
    points = dedup

    n = len(points)
    if n < 15: return []

    window = 5
    for i in range(n):
        j = max(0, i - window)
        dt = points[i]["time"] - points[j]["time"]
        points[i]["v_rate_smooth"] = ((points[i]["alt_ft"] - points[j]["alt_ft"]) / dt) * 60.0 if dt > 0 else 0.0

    dives = []
    for i, p in enumerate(points):
        if p["v_rate_smooth"] <= -2000:
            if not dives or (p["time"] - points[dives[-1]]["time"] > 600):
                dives.append(i)

    runs = []
    for d_idx in dives:
        dive_time = points[d_idx]["time"]
        candidates = [p for p in points if dive_time - 180 <= p["time"] <= dive_time]
        if not candidates: continue
        max_alt = max(p["alt_m"] for p in candidates)

        run_seg = []
        for p in reversed(candidates):
            if p["alt_m"] >= 2800 and (max_alt - p["alt_m"] <= 350) and (30 <= p["speed_kt"] <= 105):
                if p.get("v_rate_smooth", 0) <= 800:
                    run_seg.insert(0, p)
                else:
                    if len(run_seg) >= 5: break
            else:
                if len(run_seg) >= 5: break

        if len(run_seg) >= 5:
            if (run_seg[-1]["time"] - run_seg[0]["time"]) >= 20:
                runs.append(run_seg)

    unique_runs = []
    for r in runs:
        if not unique_runs:
            unique_runs.append(r)
        else:
            if r[0]["time"] > unique_runs[-1][-1]["time"] + 30:
                unique_runs.append(r)

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
    if curr: decolli.append(curr)

    return decolli

def process_all_imports():
    fleet = load_fleet()
    dropzones = load_dropzones()
    
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
            points_by_ac_date[(matched_reg, dt.strftime("%Y-%m-%d"))].append(p)

    with open(INDEX_PATH, "r") as f:
        master_index = json.load(f)
    
    if "dropzones" not in master_index:
        master_index["dropzones"] = []

    total_runs_imported = 0

    for (reg, d_str), raw_points in sorted(points_by_ac_date.items()):
        decolli = extract_jump_runs_by_decollo(raw_points)
        print(f"\n🗓️  {reg} - Data {d_str}: estratti {len(decolli)} decolli completi.")

        for d_idx, runs_in_dec in enumerate(decolli, 1):
            for r_idx, run_segment in enumerate(runs_in_dec, 1):
                start_lat, start_lon = run_segment[0]["lat"], run_segment[0]["lon"]
                matched_dz = find_closest_dz(start_lat, start_lon, dropzones)
                
                if not matched_dz:
                    print(f"  ⚠️ Lancio ignorato: Nessuna dropzone nel raggio di 50km (Lat: {start_lat:.3f}, Lon: {start_lon:.3f})")
                    continue
                
                dz_id = matched_dz["id"]
                dz_name = matched_dz["name"]
                model = fleet.get(reg, {}).get("model", "Aereo da lancio")
                photo = fleet.get(reg, {}).get("photo", "")
                
                dz_dir = os.path.join(RUNS_DIR, dz_id)
                os.makedirs(dz_dir, exist_ok=True)

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
                run_filepath = os.path.join(dz_dir, run_filename)

                run_data = {
                    "dropzone_id": dz_id,
                    "dropzone": dz_name,
                    "reg": reg,
                    "model": model,
                    "date": d_str,
                    "time": time_str,
                    "stats": {
                        "altitude_m": exit_alt, "heading_deg": avg_track,
                        "ground_speed_kt": avg_speed, "separation_sec": sep_300m, "duration_sec": duration
                    },
                    "points": [{"lat": p["lat"], "lon": p["lon"]} for p in run_segment]
                }
                with open(run_filepath, "w") as rf: json.dump(run_data, rf, indent=2)

                dz_entry = next((d for d in master_index["dropzones"] if d["id"] == dz_id), None)
                if not dz_entry:
                    dz_entry = {"id": dz_id, "name": dz_name, "active_reg": reg, "model": model, "photo": photo, "center_lat": matched_dz["center_lat"], "center_lon": matched_dz["center_lon"], "runs": []}
                    master_index["dropzones"].append(dz_entry)
                
                dz_entry["runs"] = [x for x in dz_entry["runs"] if x["file"] != f"{dz_id}/{run_filename}"]
                dz_entry["runs"].append({
                    "file": f"{dz_id}/{run_filename}", "reg": reg, "date": d_str, "time": time_str,
                    "title": title, "duration_sec": duration, "heading_deg": avg_track, "speed_kt": avg_speed
                })
                dz_entry["runs"].sort(key=lambda x: (x.get("date", ""), x.get("time", "")), reverse=True)
                # Allinea l aereo attivo all ultimo lancio registrato
                if dz_entry["runs"]:
                    dz_entry["active_reg"] = dz_entry["runs"][0]["reg"]
                    dz_entry["model"] = fleet.get(dz_entry["active_reg"], {}).get("model", dz_entry.get("model", ""))
                    dz_entry["photo"] = fleet.get(dz_entry["active_reg"], {}).get("photo", dz_entry.get("photo", ""))

                total_runs_imported += 1
                dur_m, dur_s = divmod(duration, 60)
                print(f"   ▶ {title} @ {dz_name} [{time_str} UTC] Durata: {dur_m}m {dur_s:02d}s | Quota: {exit_alt}m | Asse: {avg_track}°")

    if total_runs_imported > 0:
        master_index["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(INDEX_PATH, "w") as f: json.dump(master_index, f, indent=2)

        print("\n☁️  Sincronizzazione su GitHub in corso...")
        subprocess.run(["git", "-C", REPO_DIR, "add", "."], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "commit", "-m", f"Importazione CSV: {total_runs_imported} lanci smistati per dropzone"], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "pull", "--rebase", "origin", "main"], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "push"], check=True)
        print("✅ Storico aggiornato e inviato a GitHub Pages!")
    else:
        print("Nessun nuovo lancio importato.")

if __name__ == "__main__":
    process_all_imports()
