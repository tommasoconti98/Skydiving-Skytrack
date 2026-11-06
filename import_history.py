import os
import csv
import json
import datetime
import subprocess

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

    points.sort(key=lambda x: x["time"])
    return points

def extract_jump_runs_by_decollo(points):
    """Isola i run-in e li raggruppa cronologicamente per decollo/ciclo di salita."""
    if len(points) < 10:
        return []

    # Calcolo variometro (ft/min)
    for i in range(1, len(points)):
        dt = points[i]["time"] - points[i - 1]["time"]
        points[i]["v_rate_fpm"] = ((points[i]["alt_ft"] - points[i - 1]["alt_ft"]) / dt * 60.0) if dt > 0 else 0.0
    points[0]["v_rate_fpm"] = 0.0

    # Rilevamento picchiate post-lancio (< -1500 ft/min)
    descents = [i for i, p in enumerate(points) if p["v_rate_fpm"] < -1500]
    if not descents:
        return []

    dive_events = []
    curr_event = [descents[0]]
    for i in range(1, len(descents)):
        if descents[i] - descents[i - 1] <= 3:
            curr_event.append(descents[i])
        else:
            dive_events.append(curr_event)
            curr_event = [descents[i]]
    dive_events.append(curr_event)

    all_runs = []
    for event in dive_events:
        dive_start = event[0]
        run_seg = []
        # Cerca all'indietro il tratto livellato del lancio
        for i in range(dive_start - 1, max(-1, dive_start - 35), -1):
            p = points[i]
            if p["alt_m"] >= 2800 and abs(p["v_rate_fpm"]) < 1000 and 50 <= p["speed_kt"] <= 120:
                run_seg.insert(0, p)
            else:
                if len(run_seg) > 0:
                    break
        if len(run_seg) >= 4:
            all_runs.append(run_seg)

    # Rimuove sovrapposizioni
    unique_runs = []
    for r in all_runs:
        if not unique_runs or r[0]["time"] > unique_runs[-1][-1]["time"] + 30:
            unique_runs.append(r)

    # Raggruppa i lanci per ciclo di decollo (stacco di oltre 15 minuti tra un volo e l'altro)
    decolli = []
    curr_decollo = []
    for r in unique_runs:
        if not curr_decollo:
            curr_decollo.append(r)
        else:
            if r[0]["time"] - curr_decollo[-1][-1]["time"] > 900:
                decolli.append(curr_decollo)
                curr_decollo = [r]
            else:
                curr_decollo.append(r)
    if curr_decollo:
        decolli.append(curr_decollo)

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

    with open(INDEX_PATH, "r") as f:
        master_index = json.load(f)

    total_imported = 0

    for fname in csv_files:
        fpath = os.path.join(IMPORTS_DIR, fname)
        matched_reg = None
        for reg in fleet.keys():
            if reg.replace("-", "").upper() in fname.upper() or reg.upper() in fname.upper():
                matched_reg = reg
                break

        if not matched_reg:
            print(f"⚠️ Nessun aereo della flotta corrisponde al file: {fname}")
            continue

        raw_points = parse_fr24_csv(fpath)
        decolli = extract_jump_runs_by_decollo(raw_points)
        print(f"📄 Analisi {fname}: individuati {len(decolli)} decolli.")

        ac_dir = os.path.join(RUNS_DIR, matched_reg)
        os.makedirs(ac_dir, exist_ok=True)

        for d_idx, runs_in_decollo in enumerate(decolli, 1):
            for r_idx, run_segment in enumerate(runs_in_decollo, 1):
                duration = int(run_segment[-1]["time"] - run_segment[0]["time"])
                avg_speed = round(sum(p["speed_kt"] for p in run_segment) / len(run_segment), 1)
                avg_track = int(sum(p["track"] for p in run_segment) / len(run_segment))
                exit_alt = run_segment[0]["alt_m"]

                speed_mps = avg_speed * 0.514444
                sep_300m = round(300.0 / speed_mps, 1) if speed_mps > 0 else 0

                dt = datetime.datetime.fromtimestamp(run_segment[0]["time"], tz=datetime.timezone.utc)
                date_str = dt.strftime("%Y-%m-%d")
                time_str = dt.strftime("%H:%M")

                title = f"Decollo #{d_idx}" if len(runs_in_decollo) == 1 else f"Decollo #{d_idx} (Lancio {r_idx})"
                run_filename = f"{date_str}_dec_{d_idx:02d}_{r_idx:02d}.json"
                run_filepath = os.path.join(ac_dir, run_filename)

                run_data = {
                    "reg": matched_reg,
                    "dropzone": fleet[matched_reg]["name"],
                    "date": date_str,
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
                    if ac_entry["reg"] == matched_reg:
                        # Rimuove duplicati se rieseguito
                        ac_entry["runs"] = [x for x in ac_entry["runs"] if x["file"] != f"{matched_reg}/{run_filename}"]
                        ac_entry["runs"].append({
                            "file": f"{matched_reg}/{run_filename}",
                            "date": date_str,
                            "time": time_str,
                            "title": title,
                            "duration_sec": duration,
                            "heading_deg": avg_track,
                            "speed_kt": avg_speed
                        })
                        ac_entry["runs"].sort(key=lambda x: f"{x['date']} {x['time']}", reverse=True)
                        break

                total_imported += 1
                print(f"  ✅ {title} [{time_str} UTC] -> Quota: {exit_alt}m | Asse: {avg_track}° | GS: {avg_speed}kt | Sep: {sep_300m}s")

    if total_imported > 0:
        master_index["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(INDEX_PATH, "w") as f:
            json.dump(master_index, f, indent=2)

        print("\nSincronizzazione archivio su GitHub Pages in corso...")
        subprocess.run(["git", "-C", REPO_DIR, "add", "."], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "commit", "-m", f"Importati {total_imported} decolli storici"], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "push"], check=True)
        print("🎉 Fatto! Tutti i decolli sono online.")

if __name__ == "__main__":
    process_all_imports()
