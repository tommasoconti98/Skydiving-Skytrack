import os
import time
import math
import json
import datetime
import subprocess
import requests

REPO_DIR = os.path.expanduser("~/Skydiving-Skytrack")
AIRCRAFT_CONFIG = os.path.join(REPO_DIR, "aircraft.json")
DATA_DIR = os.path.join(REPO_DIR, "data")
RUNS_DIR = os.path.join(DATA_DIR, "runs")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.flightradar24.com/",
    "Origin": "https://www.flightradar24.com"
}

def load_fleet_config():
    if not os.path.exists(AIRCRAFT_CONFIG):
        return {}
    try:
        with open(AIRCRAFT_CONFIG, "r") as f:
            fleet_list = json.load(f)
            return {ac["reg"]: ac for ac in fleet_list}
    except Exception as e:
        print("Errore lettura aircraft.json:", e)
        return {}

def ensure_master_index(fleet_dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(RUNS_DIR, exist_ok=True)
    index_path = os.path.join(DATA_DIR, "index.json")

    if not os.path.exists(index_path):
        data = {"aircrafts": [], "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    else:
        try:
            with open(index_path, "r") as f:
                data = json.load(f)
        except Exception:
            data = {"aircrafts": [], "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat()}

    existing_regs = {ac["reg"] for ac in data.get("aircrafts", [])}
    for reg, info in fleet_dict.items():
        if reg not in existing_regs:
            data["aircrafts"].append({
                "reg": reg,
                "name": f"{reg} - {info['name']}",
                "model": info.get("model", ""),
                "runs": []
            })

    with open(index_path, "w") as f:
        json.dump(data, f, indent=2)

def get_fr24_url(lat, lon, radius_km):
    delta_lat = radius_km / 111.0
    delta_lon = radius_km / (111.0 * math.cos(math.radians(lat)))
    return (
        f"https://data-cloud.flightradar24.com/zones/fcgi/feed.js?"
        f"bounds={lat+delta_lat:.4f},{lat-delta_lat:.4f},{lon-delta_lon:.4f},{lon+delta_lon:.4f}"
        f"&faa=1&satellite=1&mlat=1&flarm=1&adsb=1&gnd=0&air=1&vehicles=0&estimated=1"
    )

class RunTracker:
    def __init__(self, reg, info):
        self.reg = reg
        self.info = info
        self.state = "IDLE"
        self.buffer = []

    def process_point(self, lat, lon, track, alt_ft, speed_kt, v_rate_fpm):
        now = time.time()
        alt_m = int(alt_ft * 0.3048)

        point = {
            "time": now, "lat": lat, "lon": lon, "track": track,
            "alt_m": alt_m, "speed_kt": speed_kt, "v_rate": v_rate_fpm
        }

        if self.state == "IDLE":
            if alt_m >= 2800 and abs(v_rate_fpm) < 500 and 65 <= speed_kt <= 110:
                print(f"[{self.reg}] Inizio RUN-IN a {alt_m}m!")
                self.state = "RUN_IN"
                self.buffer = [point]

        elif self.state == "RUN_IN":
            self.buffer.append(point)

            if v_rate_fpm <= -1800:
                print(f"[{self.reg}] Fine RUN-IN (Picchiata: {v_rate_fpm} ft/min).")
                if len(self.buffer) >= 6:
                    self.finalize_run()
                self.reset()
            elif (now - self.buffer[0]["time"]) > 240:
                print(f"[{self.reg}] Timeout durata superato.")
                self.reset()

    def finalize_run(self):
        duration = int(self.buffer[-1]["time"] - self.buffer[0]["time"])
        avg_speed = round(sum(p["speed_kt"] for p in self.buffer) / len(self.buffer), 1)
        avg_track = int(sum(p["track"] for p in self.buffer) / len(self.buffer))
        exit_alt = self.buffer[0]["alt_m"]

        speed_mps = avg_speed * 0.514444
        sep_300m = round(300.0 / speed_mps, 1) if speed_mps > 0 else 0

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        date_str = now_dt.strftime("%Y-%m-%d")
        time_str = now_dt.strftime("%H:%M")

        ac_dir = os.path.join(RUNS_DIR, self.reg)
        os.makedirs(ac_dir, exist_ok=True)
        today_runs = [f for f in os.listdir(ac_dir) if f.startswith(date_str)]
        run_num = len(today_runs) + 1

        file_name = f"{date_str}_run_{run_num:02d}.json"
        file_path = os.path.join(ac_dir, file_name)

        run_data = {
            "reg": self.reg,
            "dropzone": self.info["name"],
            "date": date_str,
            "time": time_str,
            "stats": {
                "altitude_m": exit_alt,
                "heading_deg": avg_track,
                "ground_speed_kt": avg_speed,
                "separation_sec": sep_300m,
                "duration_sec": duration
            },
            "points": [{"lat": p["lat"], "lon": p["lon"]} for p in self.buffer]
        }

        with open(file_path, "w") as f:
            json.dump(run_data, f, indent=2)

        print(f"[{self.reg}] File run scritto: {file_name}")
        update_master_index(self.reg, file_name, date_str, time_str, duration, avg_track, avg_speed)
        clean_old_runs()
        push_to_github(f"Nuovo lancio {self.reg} #{run_num} - {date_str}")

    def reset(self):
        self.state = "IDLE"
        self.buffer = []

def update_master_index(reg, rel_file, date_str, time_str, duration, heading, speed):
    index_path = os.path.join(DATA_DIR, "index.json")
    with open(index_path, "r") as f:
        data = json.load(f)

    for ac in data["aircrafts"]:
        if ac["reg"] == reg:
            run_entry = {
                "file": f"{reg}/{rel_file}",
                "date": date_str,
                "time": time_str,
                "title": f"Lancio #{len(ac['runs']) + 1}",
                "duration_sec": duration,
                "heading_deg": heading,
                "speed_kt": speed
            }
            ac["runs"].insert(0, run_entry)
            break

    data["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(index_path, "w") as f:
        json.dump(data, f, indent=2)

def clean_old_runs():
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
    index_path = os.path.join(DATA_DIR, "index.json")
    with open(index_path, "r") as f:
        data = json.load(f)

    for ac in data["aircrafts"]:
        valid = []
        for r in ac.get("runs", []):
            try:
                r_date = datetime.datetime.strptime(r["date"], "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
                if r_date >= cutoff:
                    valid.append(r)
                else:
                    path = os.path.join(RUNS_DIR, r["file"])
                    if os.path.exists(path):
                        os.remove(path)
            except Exception:
                valid.append(r)
        ac["runs"] = valid

    with open(index_path, "w") as f:
        json.dump(data, f, indent=2)

def git_pull():
    try:
        subprocess.run(["git", "-C", REPO_DIR, "pull", "--rebase"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def push_to_github(msg):
    try:
        subprocess.run(["git", "-C", REPO_DIR, "add", "."], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "commit", "-m", msg], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "push"], check=True)
        print(">> Repository sincronizzato.")
    except Exception as e:
        print("Errore push:", e)

def main():
    fleet = load_fleet_config()
    ensure_master_index(fleet)
    trackers = {reg: RunTracker(reg, info) for reg, info in fleet.items()}
    print(f"Monitor attivo su watchlist: {list(trackers.keys())}")

    last_pull_time = time.time()

    while True:
        # Controllo aggiornamenti da GitHub ogni 5 minuti
        if time.time() - last_pull_time > 300:
            git_pull()
            new_fleet = load_fleet_config()
            for r, inf in new_fleet.items():
                if r not in trackers:
                    print(f"Nuovo aereo aggiunto dinamicamente: {r}")
                    trackers[r] = RunTracker(r, inf)
            last_pull_time = time.time()

        for reg, tracker in list(trackers.items()):
            url = get_fr24_url(tracker.info["center_lat"], tracker.info["center_lon"], tracker.info["radius_km"])
            try:
                r = requests.get(url, headers=HEADERS, timeout=5)
                if r.status_code == 200:
                    feed = r.json()
                    for k, val in feed.items():
                        if k in ["full_count", "version"]: continue
                        plane_reg = val[9] if len(val) > 9 else ""
                        if plane_reg == reg:
                            lat = val[1]
                            lon = val[2]
                            trk = val[3] or 0
                            alt = val[4] or 0
                            spd = val[5] or 0
                            vrt = val[15] or 0
                            tracker.process_point(lat, lon, trk, alt, spd, vrt)
            except Exception:
                pass
        time.sleep(6)

if __name__ == "__main__":
    main()
