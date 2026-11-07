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
        print(f"❌ Errore lettura aircraft.json: {e}")
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

def circular_mean_heading(angles_deg):
    x = sum(math.cos(math.radians(a)) for a in angles_deg)
    y = sum(math.sin(math.radians(a)) for a in angles_deg)
    return round(math.degrees(math.atan2(y, x)) % 360)

class RunTracker:
    def __init__(self, reg, info):
        self.reg = reg
        self.info = info
        self.state = "IDLE"  # IDLE, RUN_IN
        self.buffer = []
        self.last_altitude_logged = 0
        self.last_seen = 0
        self.last_point = None
        self.max_alt_m = 0

    def process_point(self, lat, lon, track, alt_ft, speed_kt, feed_vrt):
        now = time.time()
        alt_m = int(alt_ft * 0.3048)
        self.last_seen = now

        # Calcolo autonomo del variometro e del rateo di virata
        calc_v_rate = feed_vrt
        turn_rate = 0.0
        if self.last_point is not None:
            dt = now - self.last_point["time"]
            if dt > 0:
                derived_vs = ((alt_ft - self.last_point["alt_ft"]) / dt) * 60.0
                if abs(feed_vrt) < 50:
                    calc_v_rate = derived_vs
                else:
                    calc_v_rate = min(feed_vrt, derived_vs)

                d_trk = abs((track - self.last_point["track"] + 180) % 360 - 180)
                turn_rate = d_trk / dt

        v_rate_fpm = calc_v_rate
        point = {
            "time": now, "lat": lat, "lon": lon, "track": track,
            "alt_m": alt_m, "alt_ft": alt_ft, "speed_kt": speed_kt, 
            "v_rate": v_rate_fpm, "turn_rate": turn_rate
        }

        # Log quota ogni 1000m di salita
        if abs(alt_m - self.last_altitude_logged) >= 1000:
            print(f"📡 [{self.reg}] Quota {alt_m}m | GS: {speed_kt} kt | V/S: {int(v_rate_fpm)} ft/min")
            self.last_altitude_logged = alt_m

        # 1. INGRESSO IN RUN-IN
        if self.state == "IDLE":
            is_level_or_slow_drift = -1000 < v_rate_fpm < 500
            is_straight = turn_rate < 3.5
            is_drop_speed = 45 <= speed_kt <= 95

            if alt_m >= 2800 and is_level_or_slow_drift and is_straight and is_drop_speed:
                print(f"🚀 [{self.reg}] INIZIO RUN-IN a {alt_m}m! (Prua: {track}°, GS: {speed_kt}kt)")
                self.state = "RUN_IN"
                self.max_alt_m = alt_m
                self.buffer = [point]

        # 2. REGISTRAZIONE RUN-IN
        elif self.state == "RUN_IN":
            if alt_m > self.max_alt_m:
                self.max_alt_m = alt_m

            # Reset se era solo una virata intermedia durante la salita
            if alt_m > (self.buffer[0]["alt_m"] + 180):
                print(f"🔄 [{self.reg}] Salita continua ({alt_m}m): ripristino monitoraggio.")
                self.reset()
                self.last_point = point
                return

            # VERA PICCHIATA:
            # - Picchiata marcata: <= -2500 ft/min
            # - Picchiata con virata/accelerazione motore: <= -1800 ft/min con GS >= 95kt o virata rapida
            # - Perdita di oltre 350m di dislivello rispetto al picco massimo del passaggio
            # - Quota scesa sotto i 2600m
            is_dive = (
                (v_rate_fpm <= -2500) or
                (v_rate_fpm <= -1800 and (speed_kt >= 95 or turn_rate > 4.0)) or
                (alt_m < (self.max_alt_m - 350)) or
                (alt_m < 2600)
            )

            if is_dive:
                print(f"🎯 [{self.reg}] PICCHIATA RILEVATA! V/S: {int(v_rate_fpm)} ft/min (Quota: {alt_m}m).")
                self.finalize_run()
                self.reset()
            else:
                self.buffer.append(point)
                # Timeout di sicurezza: se dopo 180s non ha ancora picchiato, salva il passaggio
                if (now - self.buffer[0]["time"]) > 180:
                    print(f"⏱️ [{self.reg}] Chiusura run-in per timeout durata (180s).")
                    self.finalize_run()
                    self.reset()

        self.last_point = point

    def check_signal_timeout(self):
        """Salva il lancio se l'aereo sparisce dal radar mentre scendeva."""
        if self.state == "RUN_IN" and self.last_seen > 0:
            if (time.time() - self.last_seen) > 25:
                print(f"🎯 [{self.reg}] Segnale radar perso in discesa: finalizzazione lancio in corso...")
                self.finalize_run()
                self.reset()

    def finalize_run(self):
        # Mantiene tutti i punti del volo livellato escludendo solo l'istante della picchiata
        run_pts = [p for p in self.buffer if p["v_rate"] > -2000]
        if len(run_pts) < 4:
            run_pts = self.buffer

        if len(run_pts) < 4:
            return

        duration = int(run_pts[-1]["time"] - run_pts[0]["time"])
        if duration < 15:
            return

        avg_speed = round(sum(p["speed_kt"] for p in run_pts) / len(run_pts), 1)
        avg_track = circular_mean_heading([p["track"] for p in run_pts])
        exit_alt = run_pts[0]["alt_m"]

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
            "points": [{"lat": p["lat"], "lon": p["lon"]} for p in run_pts]
        }

        with open(file_path, "w") as f:
            json.dump(run_data, f, indent=2)

        print(f"💾 [{self.reg}] Lancio #{run_num} salvato! (Durata: {duration}s, Asse: {avg_track}°, GS: {avg_speed}kt, Quota: {exit_alt}m, Sep: {sep_300m}s)")
        update_master_index(self.reg, file_name, date_str, time_str, duration, avg_track, avg_speed)
        clean_old_runs()
        push_to_github(f"Nuovo lancio {self.reg} #{run_num} - {date_str}")

    def reset(self):
        self.state = "IDLE"
        self.buffer = []
        self.max_alt_m = 0

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
                "title": f"Decollo #{len(ac['runs']) + 1}",
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
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=90)
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
        print("☁️ Repository GitHub aggiornato in diretta!")
    except Exception as e:
        print(f"❌ Errore sincronizzazione GitHub: {e}")

def main():
    git_pull()
    fleet = load_fleet_config()
    ensure_master_index(fleet)
    trackers = {reg: RunTracker(reg, info) for reg, info in fleet.items()}
    print(f"🟢 SkyTrack Monitor avviato! Aerei monitorati: {list(trackers.keys())}")

    last_pull_time = time.time()
    last_heartbeat = time.time()

    while True:
        now = time.time()

        if now - last_pull_time > 86400:
            git_pull()
            new_fleet = load_fleet_config()
            for r, inf in new_fleet.items():
                if r not in trackers:
                    trackers[r] = RunTracker(r, inf)
            last_pull_time = now

        if now - last_heartbeat > 1800:
            print(f"💓 [HEARTBEAT] Monitor attivo su {len(trackers)} dropzone.")
            last_heartbeat = now

        for reg, tracker in list(trackers.items()):
            url = get_fr24_url(tracker.info["center_lat"], tracker.info["center_lon"], tracker.info["radius_km"])
            try:
                r = requests.get(url, headers=HEADERS, timeout=5)
                if r.status_code == 200:
                    feed = r.json()
                    plane_found = False
                    for k, val in feed.items():
                        if k in ["full_count", "version"]: continue
                        plane_reg = val[9] if len(val) > 9 else ""
                        if plane_reg == reg:
                            plane_found = True
                            lat = val[1]
                            lon = val[2]
                            trk = val[3] or 0
                            alt = val[4] or 0
                            spd = val[5] or 0
                            vrt = val[15] or 0
                            tracker.process_point(lat, lon, trk, alt, spd, vrt)

                    if not plane_found:
                        tracker.check_signal_timeout()
            except Exception:
                pass

        time.sleep(6)

if __name__ == "__main__":
    main()
