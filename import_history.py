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

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def circular_mean_heading(angles_deg):
    x = sum(math.cos(math.radians(a)) for a in angles_deg)
    y = sum(math.sin(math.radians(a)) for a in angles_deg)
    return round(math.degrees(math.atan2(y, x)) % 360)

def angle_diff_deg(a, b):
    return abs((a - b + 180) % 360 - 180)

def match_reg_from_text(text, fleet):
    if not text:
        return None
    clean = text.replace("-", "").upper()
    for reg in fleet.keys():
        if reg.replace("-", "").upper() in clean or reg.upper() in text.upper():
            return reg
    return None

def parse_fr24_csv(filepath):
    points = []
    detected_callsigns = set()
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                cs = (row.get("Callsign") or row.get("Registration") or "").strip()
                if cs:
                    detected_callsigns.add(cs)

                ts = int(row.get("Timestamp") or 0)
                if not ts:
                    continue

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
    return points, detected_callsigns

def find_closest_dz(points, dropzones):
    best_dz = None
    best_dist = float("inf")
    for dz in dropzones:
        d = min(haversine_m(p["lat"], p["lon"], dz["center_lat"], dz["center_lon"]) for p in points)
        if d < best_dist:
            best_dist = d
            best_dz = dz
    if best_dz and best_dist <= 2500.0:
        return best_dz
    return None

def extract_runs_for_dz(points, dz, model_str):
    if len(points) < 10:
        return []

    points = sorted(points, key=lambda x: x["time"])
    dedup = [points[0]]
    for p in points[1:]:
        if p["time"] != dedup[-1]["time"]:
            dedup.append(p)
    points = dedup

    m_low = model_str.lower()
    if "c208" in m_low or "caravan" in m_low:
        min_alt_m, min_spd_kt, max_spd_kt = 2700, 50, 110
        dive_vs_fpm, dive_combo_vs, dive_combo_spd = -2200, -1600, 105
    elif "206" in m_low or "207" in m_low:
        min_alt_m, min_spd_kt, max_spd_kt = 2400, 35, 90
        dive_vs_fpm, dive_combo_vs, dive_combo_spd = -1600, -1300, 85
    else:
        min_alt_m, min_spd_kt, max_spd_kt = 2700, 35, 95
        dive_vs_fpm, dive_combo_vs, dive_combo_spd = -2400, -1800, 95

    clat, clon = dz["center_lat"], dz["center_lon"]

    # Campionamento a 6s allineato al polling live del radar
    sampled = []
    last_ts = 0
    for p in points:
        if p["time"] - last_ts >= 6:
            sampled.append(p)
            last_ts = p["time"]

    state = "IDLE"
    buf = []
    last_point = None
    last_seen = 0
    max_alt_m = 0
    turn_away_streak = 0
    ready_for_new_load = True
    load_num = 0
    pass_num = 0
    last_pass_end = 0
    extracted = []

    def finalize_segment():
        nonlocal load_num, pass_num, ready_for_new_load, last_pass_end
        run_pts = [p for p in buf if p["v_rate"] > dive_vs_fpm]
        if len(run_pts) < 4:
            run_pts = buf
        if len(run_pts) < 4:
            return
        duration = int(run_pts[-1]["time"] - run_pts[0]["time"])
        if duration < 15:
            return

        total_dt = run_pts[-1]["time"] - run_pts[0]["time"]
        if total_dt > 0:
            overall_vs = ((run_pts[-1]["alt_ft"] - run_pts[0]["alt_ft"]) / total_dt) * 60.0
            if overall_vs > 300:
                return

        avg_speed = round(sum(p["speed_kt"] for p in run_pts) / len(run_pts), 1)
        min_dist_dz = min(p["dist_dz"] for p in run_pts)
        max_allowed = 1550 if avg_speed < 85 else 1250
        if min_dist_dz > max_allowed:
            return

        last_pass_end = run_pts[-1]["time"]
        if ready_for_new_load:
            load_num += 1
            pass_num = 1
            ready_for_new_load = False
        else:
            pass_num += 1
            if pass_num == 2 and extracted:
                extracted[-1]["pass_num"] = 1
                extracted[-1]["is_multi"] = True

        extracted.append({
            "load_num": load_num,
            "pass_num": pass_num,
            "is_multi": pass_num > 1,
            "points": run_pts,
            "duration": duration,
            "avg_speed": avg_speed
        })

    for p in sampled:
        now = p["time"]
        if state == "RUN_IN" and last_seen > 0 and (now - last_seen) > 25:
            finalize_segment()
            state, buf, max_alt_m, turn_away_streak = "IDLE", [], 0, 0

        if last_seen > 0 and (now - last_seen) > 240:
            ready_for_new_load = True

        last_seen = now
        lat, lon, track, alt_ft, speed_kt = p["lat"], p["lon"], p["track"], p["alt_ft"], p["speed_kt"]

        if last_point and abs(lat - last_point["lat"]) < 0.00001 and abs(lon - last_point["lon"]) < 0.00001:
            continue

        alt_m = int(alt_ft * 0.3048)
        dist_dz = haversine_m(lat, lon, clat, clon)

        if alt_m < (min_alt_m - 400):
            ready_for_new_load = True

        v_rate_fpm = 0.0
        turn_rate = 0.0
        if last_point:
            dt = now - last_point["time"]
            if dt > 0:
                v_rate_fpm = ((alt_ft - last_point["alt_ft"]) / dt) * 60.0
                d_trk = abs((track - last_point["track"] + 180) % 360 - 180)
                turn_rate = d_trk / dt

        pt = {
            "time": now, "lat": lat, "lon": lon, "track": track,
            "alt_m": alt_m, "alt_ft": alt_ft, "speed_kt": speed_kt,
            "v_rate": v_rate_fpm, "dist_dz": dist_dz
        }

        if state == "IDLE":
            if dist_dz <= 2500 and (now - last_pass_end) > 25:
                if alt_m >= min_alt_m and -1000 < v_rate_fpm < 800 and turn_rate < 4.5 and min_spd_kt <= speed_kt <= max_spd_kt:
                    state = "RUN_IN"
                    max_alt_m = alt_m
                    turn_away_streak = 0
                    buf = [pt]
        elif state == "RUN_IN":
            if alt_m > max_alt_m:
                max_alt_m = alt_m

            if alt_m > (buf[0]["alt_m"] + 120):
                state, buf, max_alt_m, turn_away_streak = "IDLE", [], 0, 0
                last_point = pt
                continue

            buf_dt = now - buf[0]["time"]
            if buf_dt >= 15:
                overall_vs = ((alt_ft - buf[0]["alt_ft"]) / buf_dt) * 60.0
                if overall_vs > 350:
                    state, buf, max_alt_m, turn_away_streak = "IDLE", [], 0, 0
                    last_point = pt
                    continue

            ref_hdg = circular_mean_heading([x["track"] for x in buf[:min(4, len(buf))]])
            hdg_dev = angle_diff_deg(track, ref_hdg)
            if len(buf) >= 3 and hdg_dev > 48:
                turn_away_streak += 1
            else:
                turn_away_streak = 0

            is_turning_away = (turn_away_streak >= 2)
            is_dive = (v_rate_fpm <= dive_vs_fpm) or \
                      (v_rate_fpm <= dive_combo_vs and (speed_kt >= dive_combo_spd or turn_rate > 4.0)) or \
                      (alt_m < (max_alt_m - 350)) or \
                      (alt_m < (min_alt_m - 200))

            if is_dive or dist_dz > 2500 or is_turning_away:
                finalize_segment()
                state, buf, max_alt_m, turn_away_streak = "IDLE", [], 0, 0
                if is_turning_away and not is_dive and dist_dz <= 2500 and (now - last_pass_end) > 25:
                    if alt_m >= min_alt_m and -1000 < v_rate_fpm < 800 and min_spd_kt <= speed_kt <= max_spd_kt:
                        state = "RUN_IN"
                        max_alt_m = alt_m
                        buf = [pt]
            else:
                buf.append(pt)
                if (now - buf[0]["time"]) > 240:
                    finalize_segment()
                    state, buf, max_alt_m, turn_away_streak = "IDLE", [], 0, 0

        last_point = pt

    if state == "RUN_IN":
        finalize_segment()

    return extracted

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
        pts, callsigns = parse_fr24_csv(fpath)

        matched_reg = match_reg_from_text(fname, fleet)
        if not matched_reg:
            for cs in callsigns:
                matched_reg = match_reg_from_text(cs, fleet)
                if matched_reg:
                    break

        if not matched_reg:
            print(f"⚠️ Ignorato file non associabile alla flotta: {fname}")
            continue

        for p in pts:
            dt = datetime.datetime.fromtimestamp(p["time"], tz=datetime.timezone.utc)
            points_by_ac_date[(matched_reg, dt.strftime("%Y-%m-%d"))].append(p)

    with open(INDEX_PATH, "r") as f:
        master_index = json.load(f)
    
    if "dropzones" not in master_index:
        master_index["dropzones"] = []

    total_runs_imported = 0

    for (reg, d_str), raw_points in sorted(points_by_ac_date.items()):
        matched_dz = find_closest_dz(raw_points, dropzones)
        if not matched_dz:
            print(f"⚠️  {reg} ({d_str}): Nessuna dropzone nel raggio di 2.5km.")
            continue

        dz_id = matched_dz["id"]
        dz_name = matched_dz["name"]
        model = fleet.get(reg, {}).get("model", "Aereo da lancio")
        photo = fleet.get(reg, {}).get("photo", "")

        extracted = extract_runs_for_dz(raw_points, matched_dz, model)
        print(f"\n🗓️  {reg} @ {dz_name} - Data {d_str}: estratti {len(extracted)} lanci validi.")

        if not extracted:
            continue

        dz_dir = os.path.join(RUNS_DIR, dz_id)
        os.makedirs(dz_dir, exist_ok=True)

        # Pulisce eventuali vecchie tracce dello stesso giorno/aereo per evitare duplicati
        for old_f in os.listdir(dz_dir):
            if old_f.startswith(d_str) and old_f.endswith(".json"):
                try:
                    with open(os.path.join(dz_dir, old_f), "r") as of:
                        old_data = json.load(of)
                    if old_data.get("reg") == reg:
                        os.remove(os.path.join(dz_dir, old_f))
                except Exception:
                    pass

        dz_entry = next((d for d in master_index["dropzones"] if d["id"] == dz_id), None)
        if not dz_entry:
            dz_entry = {
                "id": dz_id, "name": dz_name, "active_reg": reg, "model": model,
                "photo": photo, "center_lat": matched_dz["center_lat"],
                "center_lon": matched_dz["center_lon"], "runs": []
            }
            master_index["dropzones"].append(dz_entry)

        dz_entry["runs"] = [
            x for x in dz_entry["runs"]
            if not (x.get("date") == d_str and x.get("reg") == reg)
        ]

        for item in extracted:
            run_segment = item["points"]
            load_num = item["load_num"]
            pass_num = item["pass_num"]
            is_multi = item["is_multi"]
            duration = item["duration"]
            avg_speed = item["avg_speed"]

            avg_track = circular_mean_heading([p["track"] for p in run_segment])
            exit_alt = run_segment[0]["alt_m"]
            speed_mps = avg_speed * 0.514444
            sep_300m = round(300.0 / speed_mps, 1) if speed_mps > 0 else 0

            dt = datetime.datetime.fromtimestamp(run_segment[0]["time"], tz=datetime.timezone.utc)
            time_str = dt.strftime("%H:%M")

            if is_multi:
                title = f"Decollo #{load_num}_{pass_num}"
                run_filename = f"{d_str}_run_{load_num:02d}_{pass_num}.json"
            else:
                title = f"Decollo #{load_num}"
                run_filename = f"{d_str}_run_{load_num:02d}.json"

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
            with open(run_filepath, "w") as rf:
                json.dump(run_data, rf, indent=2)

            dz_entry["runs"].append({
                "file": f"{dz_id}/{run_filename}", "reg": reg, "date": d_str, "time": time_str,
                "title": title, "duration_sec": duration, "heading_deg": avg_track, "speed_kt": avg_speed
            })

            total_runs_imported += 1
            dur_m, dur_s = divmod(duration, 60)
            print(f"   ▶ {title} @ {dz_name} [{time_str} UTC] Durata: {dur_m}m {dur_s:02d}s | Quota: {exit_alt}m | Asse: {avg_track}°")

        dz_entry["runs"].sort(key=lambda x: (x.get("date", ""), x.get("time", "")), reverse=True)
        if dz_entry["runs"]:
            dz_entry["active_reg"] = dz_entry["runs"][0]["reg"]
            dz_entry["model"] = fleet.get(dz_entry["active_reg"], {}).get("model", dz_entry.get("model", ""))
            dz_entry["photo"] = fleet.get(dz_entry["active_reg"], {}).get("photo", dz_entry.get("photo", ""))

    if total_runs_imported > 0:
        master_index["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(INDEX_PATH, "w") as f:
            json.dump(master_index, f, indent=2)

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
