import os
import time
import math
import json
import datetime
import subprocess
import requests
import threading
import telebot

REPO_DIR = os.path.expanduser("~/Skydiving-Skytrack")
AIRCRAFT_CONFIG = os.path.join(REPO_DIR, "aircraft.json")
DATA_DIR = os.path.join(REPO_DIR, "data")
RUNS_DIR = os.path.join(DATA_DIR, "runs")
INDEX_PATH = os.path.join(DATA_DIR, "index.json")
TELEGRAM_USERS_FILE = os.path.join(DATA_DIR, "telegram_users.json")

# ================= TELEGRAM CONFIG =================
BOT_TOKEN = "9201777349:AAGtvUAgMs9aiTzMUYgfmlXsEhAlmx1tt3M"
bot = telebot.TeleBot(BOT_TOKEN)

# ================= FUNZIONI TELEGRAM ===============
def load_telegram_users():
    if os.path.exists(TELEGRAM_USERS_FILE):
        try:
            with open(TELEGRAM_USERS_FILE, "r") as f:
                return json.load(f)
        except: pass
    return {}

def save_telegram_users(users):
    with open(TELEGRAM_USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def broadcast_telegram(reg, message):
    users = load_telegram_users()
    for chat_id, sub_reg in users.items():
        if sub_reg == reg or sub_reg == "ALL":
            try:
                bot.send_message(chat_id, message, parse_mode="Markdown")
            except Exception as e:
                print(f"Errore invio Telegram a {chat_id}: {e}")

@bot.message_handler(commands=['start'])
def handle_start(message):
    bot.reply_to(message, "✈️ *Benvenuto su SkyTrack Bot!*\nUsa /lista per vedere gli aerei disponibili e iscriverti alle notifiche.", parse_mode="Markdown")

@bot.message_handler(commands=['stato'])
def handle_stato(message):
    bot.reply_to(message, "🟢 *Sistema Online*\nIl radar è attivo e sta monitorando le dropzone.", parse_mode="Markdown")

@bot.message_handler(commands=['lista'])
def handle_lista(message):
    fleet = load_fleet_config()
    msg = "📋 *Aerei disponibili:*\n\n"
    for reg, info in fleet.items():
        clean_cmd = reg.replace("-", "").upper()
        msg += f"• *{reg}* ({info['name']})\n  👉 Premi: /{clean_cmd}\n\n"
    msg += "Clicca sul comando dell'aereo che vuoi seguire per ricevere solo i suoi aggiornamenti."
    bot.reply_to(message, msg, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text.startswith('/'))
def handle_custom_command(message):
    cmd = message.text[1:].upper()
    fleet = load_fleet_config()
    
    # Mappa il comando (es. DFGMG) alla sigla reale (D-FGMG)
    target_reg = None
    for reg in fleet.keys():
        if reg.replace("-", "").upper() == cmd:
            target_reg = reg
            break
            
    if target_reg:
        users = load_telegram_users()
        users[str(message.chat.id)] = target_reg
        save_telegram_users(users)
        bot.reply_to(message, f"✅ Iscrizione confermata!\nRiceverai solo le allerte per *{target_reg}* ({fleet[target_reg]['name']}).", parse_mode="Markdown")
    elif cmd not in ["START", "STATO", "LISTA"]:
        bot.reply_to(message, "Comando non riconosciuto. Usa /lista per vedere i comandi validi.")

def run_bot():
    print("🤖 Bot Telegram avviato in background.")
    bot.infinity_polling()

# ================= CORE SKYTRACK =================
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.flightradar24.com/",
    "Origin": "https://www.flightradar24.com"
}

def load_fleet_config():
    if not os.path.exists(AIRCRAFT_CONFIG): return {}
    with open(AIRCRAFT_CONFIG, "r") as f:
        return {ac["reg"]: ac for ac in json.load(f)}

def ensure_master_index(fleet_dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(RUNS_DIR, exist_ok=True)
    if not os.path.exists(INDEX_PATH):
        data = {"aircrafts": [], "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    else:
        with open(INDEX_PATH, "r") as f:
            data = json.load(f)

    existing_regs = {ac["reg"] for ac in data.get("aircrafts", [])}
    for reg, info in fleet_dict.items():
        if reg not in existing_regs:
            data["aircrafts"].append({"reg": reg, "name": f"{reg} - {info['name']}", "runs": []})
    
    with open(INDEX_PATH, "w") as f:
        json.dump(data, f, indent=2)

def circular_mean_heading(angles_deg):
    x = sum(math.cos(math.radians(a)) for a in angles_deg)
    y = sum(math.sin(math.radians(a)) for a in angles_deg)
    return round(math.degrees(math.atan2(y, x)) % 360)

class RunTracker:
    def __init__(self, reg, info):
        self.reg = reg
        self.info = info
        self.state = "IDLE"
        self.buffer = []
        self.last_seen = 0
        self.last_point = None
        self.max_alt_m = 0
        
        self.is_flying = False

    def process_point(self, lat, lon, track, alt_ft, speed_kt, feed_vrt):
        now = time.time()
        alt_m = int(alt_ft * 0.3048)
        self.last_seen = now

        calc_v_rate = feed_vrt
        turn_rate = 0.0
        if self.last_point:
            dt = now - self.last_point["time"]
            if dt > 0:
                derived_vs = ((alt_ft - self.last_point["alt_ft"]) / dt) * 60.0
                calc_v_rate = derived_vs if abs(feed_vrt) < 50 else min(feed_vrt, derived_vs)
                d_trk = abs((track - self.last_point["track"] + 180) % 360 - 180)
                turn_rate = d_trk / dt

        v_rate_fpm = calc_v_rate
        point = {"time": now, "lat": lat, "lon": lon, "track": track, "alt_m": alt_m, "alt_ft": alt_ft, "speed_kt": speed_kt, "v_rate": v_rate_fpm}

        # LOGICA DECOLLO TELEGRAM
        # Se supera i 350m e sta salendo ad almeno 400 ft/min
        if alt_m > 350 and v_rate_fpm > 400 and not self.is_flying:
            self.is_flying = True
            broadcast_telegram(self.reg, f"🛫 *Aereo in volo!*\n{self.reg} sta salendo a {alt_m}m.")

        if self.state == "IDLE":
            if alt_m >= 2800 and -1000 < v_rate_fpm < 500 and turn_rate < 3.5 and 45 <= speed_kt <= 95:
                self.state = "RUN_IN"
                self.max_alt_m = alt_m
                self.buffer = [point]

        elif self.state == "RUN_IN":
            if alt_m > self.max_alt_m: self.max_alt_m = alt_m

            if alt_m > (self.buffer[0]["alt_m"] + 180):
                self.reset()
                self.last_point = point
                return

            is_dive = (v_rate_fpm <= -2500) or (v_rate_fpm <= -1800 and (speed_kt >= 95 or turn_rate > 4.0)) or (alt_m < (self.max_alt_m - 350)) or (alt_m < 2600)
            if is_dive:
                self.finalize_run()
                self.reset()
            else:
                self.buffer.append(point)
                if (now - self.buffer[0]["time"]) > 180:
                    self.finalize_run()
                    self.reset()

        self.last_point = point

    def check_signal_timeout(self):
        now = time.time()
        # Salvataggio run-in se sparisce
        if self.state == "RUN_IN" and self.last_seen > 0 and (now - self.last_seen) > 25:
            self.finalize_run()
            self.reset()
        
        # Timeout 40 minuti (2400 sec): Aereo atterrato o fine operazioni
        if self.is_flying and self.last_seen > 0 and (now - self.last_seen) > 2400:
            self.is_flying = False
            broadcast_telegram(self.reg, f"💤 *Tracciamento in pausa*\nSegnale di {self.reg} assente da 40 minuti (Atterrato o transponder spento).")

    def finalize_run(self):
        run_pts = [p for p in self.buffer if p["v_rate"] > -2000]
        if len(run_pts) < 4: run_pts = self.buffer
        if len(run_pts) < 4: return
        
        duration = int(run_pts[-1]["time"] - run_pts[0]["time"])
        if duration < 15: return

        avg_speed = round(sum(p["speed_kt"] for p in run_pts) / len(run_pts), 1)
        avg_track = circular_mean_heading([p["track"] for p in run_pts])
        exit_alt = run_pts[0]["alt_m"]
        sep_300m = round(300.0 / (avg_speed * 0.514444), 1) if avg_speed > 0 else 0

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        d_str, t_str = now_dt.strftime("%Y-%m-%d"), now_dt.strftime("%H:%M")

        with open(INDEX_PATH, "r") as f: data = json.load(f)
        ac_entry = next((a for a in data["aircrafts"] if a["reg"] == self.reg), None)
        run_num = len([r for r in ac_entry.get("runs", []) if r.get("date") == d_str]) + 1 if ac_entry else 1

        # TELEGRAM: Riassunto Lancio
        msg = f"🪂 *Lancio Completato!*\n✈️ {self.reg} - Decollo #{run_num}\n\n"
        msg += f"📏 Quota: *{exit_alt}m*\n"
        msg += f"🧭 Asse: *{avg_track}°*\n"
        msg += f"💨 Ground Speed: *{avg_speed} kt*\n"
        msg += f"⏱ Separazione 300m: *{sep_300m} s*"
        broadcast_telegram(self.reg, msg)

        # Salvataggio File 
        ac_dir = os.path.join(RUNS_DIR, self.reg)
        os.makedirs(ac_dir, exist_ok=True)
        f_name = f"{d_str}_run_{run_num:02d}.json"
        
        run_data = {
            "reg": self.reg, "dropzone": self.info["name"], "date": d_str, "time": t_str,
            "stats": {"altitude_m": exit_alt, "heading_deg": avg_track, "ground_speed_kt": avg_speed, "separation_sec": sep_300m, "duration_sec": duration},
            "points": [{"lat": p["lat"], "lon": p["lon"]} for p in run_pts]
        }
        with open(os.path.join(ac_dir, f_name), "w") as f: json.dump(run_data, f)
        
        update_master_index(self.reg, f_name, d_str, t_str, duration, avg_track, avg_speed, run_num)
        push_to_github(f"Nuovo lancio {self.reg} #{run_num}")

    def reset(self):
        self.state = "IDLE"
        self.buffer = []
        self.max_alt_m = 0

def update_master_index(reg, rel_file, d_str, t_str, duration, heading, speed, run_num):
    with open(INDEX_PATH, "r") as f: data = json.load(f)
    for ac in data["aircrafts"]:
        if ac["reg"] == reg:
            ac["runs"].insert(0, {"file": f"{reg}/{rel_file}", "date": d_str, "time": t_str, "title": f"Decollo #{run_num}", "duration_sec": duration, "heading_deg": heading, "speed_kt": speed})
            break
    data["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(INDEX_PATH, "w") as f: json.dump(data, f, indent=2)

def push_to_github(msg):
    try:
        subprocess.run(["git", "-C", REPO_DIR, "add", "."], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "commit", "-m", msg], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "push"], check=True)
    except: pass

def main():
    threading.Thread(target=run_bot, daemon=True).start()
    
    fleet = load_fleet_config()
    ensure_master_index(fleet)
    trackers = {reg: RunTracker(reg, info) for reg, info in fleet.items()}
    
    daily_summary_sent = False

    while True:
        now_time = time.time()
        dt_now = datetime.datetime.now() # Ora locale Raspberry (CET/CEST)
        
        # Riassunto Giornaliero: Fisso alle 20:30 locali
        if dt_now.hour == 20 and dt_now.minute == 30:
            if not daily_summary_sent:
                today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
                with open(INDEX_PATH, "r") as f: data = json.load(f)
                
                for ac in data["aircrafts"]:
                    today_runs = [r for r in ac.get("runs", []) if r["date"] == today_str]
                    if today_runs:
                        msg = f"🌅 *Riassunto Giornata*\nL'aereo {ac['reg']} oggi ha completato *{len(today_runs)} decolli* registrati."
                        broadcast_telegram(ac["reg"], msg)
                daily_summary_sent = True
        else:
            daily_summary_sent = False # Resetta per il giorno successivo

        for reg, tracker in trackers.items():
            url = f"https://data-cloud.flightradar24.com/zones/fcgi/feed.js?bounds={tracker.info['center_lat']+0.3},{tracker.info['center_lat']-0.3},{tracker.info['center_lon']-0.3},{tracker.info['center_lon']+0.3}&faa=1&satellite=1&mlat=1&flarm=1&adsb=1&gnd=0&air=1&vehicles=0&estimated=1"
            try:
                r = requests.get(url, headers=HEADERS, timeout=5)
                if r.status_code == 200:
                    feed = r.json()
                    found = False
                    for k, val in feed.items():
                        if k in ["full_count", "version"]: continue
                        if (val[9] if len(val) > 9 else "") == reg:
                            found = True
                            tracker.process_point(val[1], val[2], val[3] or 0, val[4] or 0, val[5] or 0, val[15] or 0)
                    if not found: tracker.check_signal_timeout()
            except: pass
        time.sleep(6)

if __name__ == "__main__":
    main()
