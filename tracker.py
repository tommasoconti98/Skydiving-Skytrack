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
DROPZONES_FILE = os.path.join(REPO_DIR, "dropzones.json")
FLEET_FILE = os.path.join(REPO_DIR, "fleet.json")
DATA_DIR = os.path.join(REPO_DIR, "data")
RUNS_DIR = os.path.join(DATA_DIR, "runs")
INDEX_PATH = os.path.join(DATA_DIR, "index.json")
TELEGRAM_USERS_FILE = os.path.join(DATA_DIR, "telegram_users.json")
BOT_CFG_FILE = os.path.join(REPO_DIR, "bot_config.json")

# ================= TELEGRAM CONFIG =================
BOT_TOKEN = ""
if os.path.exists(BOT_CFG_FILE):
    try:
        with open(BOT_CFG_FILE, "r") as cf:
            BOT_TOKEN = json.load(cf).get("bot_token", "")
    except Exception as e:
        print(f"Errore lettura bot_config.json: {e}")

if not BOT_TOKEN:
    BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

if not BOT_TOKEN:
    print("⚠️ ATTENZIONE: Nessun BOT_TOKEN trovato in bot_config.json o env!")
    bot = None
else:
    bot = telebot.TeleBot(BOT_TOKEN)

# ================= GESTIONE UTENTI TELEGRAM ========
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

def broadcast_telegram(target_key, message):
    if not bot: return
    users = load_telegram_users()
    for chat_id, sub in users.items():
        if sub == target_key or sub == "ALL":
            try:
                bot.send_message(chat_id, message, parse_mode="Markdown")
            except Exception as e:
                print(f"Errore invio Telegram a {chat_id}: {e}")

if bot:
    @bot.message_handler(commands=['start'])
    def handle_start(message):
        bot.reply_to(message, "✈️ *Benvenuto su SkyTrack Bot!*\nUsa /lista per scegliere quale Dropzone o quale Aereo seguire.", parse_mode="Markdown")

    @bot.message_handler(commands=['stato'])
    def handle_stato(message):
        dzs = load_dropzones()
        fleet = load_fleet()
        bot.reply_to(message, f"🟢 *Sistema Online*\nIl radar sta monitorando {len(dzs)} dropzone e una flotta di {len(fleet)} velivoli.", parse_mode="Markdown")

    @bot.message_handler(commands=['lista', 'aerei', 'flotta'])
    def handle_lista(message):
        dzs = load_dropzones()
        fleet = load_fleet()
        
        msg = "📍 *DROPZONE MONITORATE:*\n"
        for dz in dzs:
            clean_cmd = dz["id"].upper()
            msg += f"• *{dz['name']}*\n  👉 Segui campo: /{clean_cmd}\n"
        
        msg += "\n✈️ *VELIVOLI MONITORATI:*\n"
        for reg, info in fleet.items():
            clean_reg = reg.replace("-", "").upper()
            model = info.get("model", "Aereo")
            msg += f"• *{reg}* ({model})\n  👉 Segui aereo: /{clean_reg}\n"
        
        msg += "\n_Clicca su un comando per attivare le notifiche._\n_Usa /stop per disattivarle in qualsiasi momento._"
        bot.reply_to(message, msg, parse_mode="Markdown")

    @bot.message_handler(commands=['stop', 'annulla', 'silenzia'])
    def handle_stop(message):
        users = load_telegram_users()
        cid = str(message.chat.id)
        if cid in users:
            del users[cid]
            save_telegram_users(users)
            bot.reply_to(message, "🔕 *Notifiche disattivate!*\nNon riceverai più aggiornamenti.\nPer riattivarle usa /lista.", parse_mode="Markdown")
        else:
            bot.reply_to(message, "ℹ️ Non avevi alcuna notifica o iscrizione attiva.\nUsa /lista per scegliere cosa seguire.", parse_mode="Markdown")

    @bot.message_handler(func=lambda msg: msg.text.startswith('/'))
    def handle_custom_command(message):
        raw_cmd = message.text[1:].split("@")[0].upper()
        cmd = raw_cmd.replace("-", "")
        dzs = load_dropzones()
        fleet = load_fleet()
        
        # 1. Match Dropzone (es. /SICILIA, /SALERNO, /LUCCA, /NETTUNO, /ORBETELLO)
        for dz in dzs:
            if dz["id"].upper() == cmd:
                users = load_telegram_users()
                users[str(message.chat.id)] = dz["id"]
                save_telegram_users(users)
                bot.reply_to(message, f"✅ Iscrizione confermata!\nRiceverai le notifiche per *{dz['name']}* (Velivolo attivo: `{dz.get('active_reg', '--')}`).", parse_mode="Markdown")
                return

        # 2. Match SOLO Marche Aereo (es. /DFWHT, /DFSKY, /DFGMG, /DFRED, /DFBUZ, /FGHEN, /DEPJR, etc.)
        for reg in fleet.keys():
            if reg.replace("-", "").upper() == cmd:
                users = load_telegram_users()
                users[str(message.chat.id)] = reg
                save_telegram_users(users)
                model = fleet[reg].get("model", "Aereo")
                bot.reply_to(message, f"✅ Iscrizione confermata per il velivolo *{reg}* ({model}).", parse_mode="Markdown")
                return

        if cmd not in ["START", "STATO", "LISTA", "AEREI", "FLOTTA", "STOP", "ANNULLA", "SILENZIA"]:
            bot.reply_to(message, "Comando non riconosciuto. Usa /lista per visualizzare l'elenco completo.")

def run_bot():
    if not bot:
        print("⚠️ Bot Telegram disattivato (manca token).")
        return
    print("🤖 Bot Telegram avviato in background.")
    bot.infinity_polling(timeout=60, long_polling_timeout=30)

# ================= CORE SKYTRACK ===================
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.flightradar24.com/",
    "Origin": "https://www.flightradar24.com"
}

def load_dropzones():
    if not os.path.exists(DROPZONES_FILE): return []
    with open(DROPZONES_FILE, "r") as f: return json.load(f)

def save_dropzones(dzs):
    with open(DROPZONES_FILE, "w") as f: json.dump(dzs, f, indent=2)

def load_fleet():
    if not os.path.exists(FLEET_FILE): return {}
    with open(FLEET_FILE, "r") as f: return json.load(f)

def ensure_master_index(dropzones, fleet):
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(RUNS_DIR, exist_ok=True)
    
    data = {"dropzones": [], "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if os.path.exists(INDEX_PATH):
        try:
            with open(INDEX_PATH, "r") as f:
                old = json.load(f)
                if "dropzones" in old:
                    data = old
        except: pass

    existing_ids = {d["id"] for d in data.get("dropzones", [])}
    for dz in dropzones:
        if dz["id"] not in existing_ids:
            reg = dz.get("active_reg", "")
            model = fleet.get(reg, {}).get("model", "Aereo da lancio")
            photo = fleet.get(reg, {}).get("photo", "")
            data["dropzones"].append({
                "id": dz["id"],
                "name": dz["name"],
                "active_reg": reg,
                "model": model,
                "photo": photo,
                "center_lat": dz["center_lat"],
                "center_lon": dz["center_lon"],
                "runs": []
            })
    
    with open(INDEX_PATH, "w") as f:
        json.dump(data, f, indent=2)

def update_dropzone_active_reg(dz_id, reg):
    dzs = load_dropzones()
    changed = False
    for d in dzs:
        if d["id"] == dz_id and d.get("active_reg") != reg:
            d["active_reg"] = reg
            changed = True
            break
    if changed:
        save_dropzones(dzs)

def circular_mean_heading(angles_deg):
    x = sum(math.cos(math.radians(a)) for a in angles_deg)
    y = sum(math.sin(math.radians(a)) for a in angles_deg)
    return round(math.degrees(math.atan2(y, x)) % 360)

class AircraftDropzoneTracker:
    def __init__(self, dz, reg, fleet):
        self.dz_id = dz["id"]
        self.dz_name = dz["name"]
        self.center_lat = dz["center_lat"]
        self.center_lon = dz["center_lon"]
        self.reg = reg
        self.fleet = fleet
        
        self.state = "IDLE"
        self.buffer = []
        self.last_seen = 0
        self.last_point = None
        self.max_alt_m = 0
        self.is_flying = False

        # Profilo di volo dinamico in base al modello di aeromobile
        model_str = self.fleet.get(self.reg, {}).get("model", "").lower()
        if "c208" in model_str or "caravan" in model_str:
            # Cessna Caravan C208: turboprop veloce in run-in
            self.min_alt_m = 2700
            self.min_spd_kt = 50
            self.max_spd_kt = 110
            self.dive_vs_fpm = -2200
            self.dive_combo_vs = -1600
            self.dive_combo_spd = 105
        elif "206" in model_str or "207" in model_str:
            # Cessna C206 / C207: aerei a pistoni (quote da 2400m+ e discese graduali salva-motore)
            self.min_alt_m = 2400
            self.min_spd_kt = 45
            self.max_spd_kt = 90
            self.dive_vs_fpm = -1600
            self.dive_combo_vs = -1300
            self.dive_combo_spd = 85
        else:
            # Pilatus PC-6 e default: STOL a turbina, quote 2700m+, picchiata ripida
            self.min_alt_m = 2700
            self.min_spd_kt = 45
            self.max_spd_kt = 95
            self.dive_vs_fpm = -2400
            self.dive_combo_vs = -1800
            self.dive_combo_spd = 95

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
        point = {
            "time": now, "lat": lat, "lon": lon, "track": track,
            "alt_m": alt_m, "alt_ft": alt_ft, "speed_kt": speed_kt, "v_rate": v_rate_fpm
        }

        # ALERT TELEGRAM: Decollo
        if alt_m > 350 and v_rate_fpm > 400 and not self.is_flying:
            self.is_flying = True
            update_dropzone_active_reg(self.dz_id, self.reg)
            model = self.fleet.get(self.reg, {}).get("model", "Aereo")
            msg = f"🛫 *Aereo in volo a {self.dz_name}!*\n*{self.reg}* ({model}) sta salendo a {alt_m}m."
            broadcast_telegram(self.dz_id, msg)
            broadcast_telegram(self.reg, msg)

        # Riconoscimento Run-In
        if self.state == "IDLE":
            if alt_m >= self.min_alt_m and -1000 < v_rate_fpm < 500 and turn_rate < 3.5 and self.min_spd_kt <= speed_kt <= self.max_spd_kt:
                self.state = "RUN_IN"
                self.max_alt_m = alt_m
                self.buffer = [point]

        elif self.state == "RUN_IN":
            if alt_m > self.max_alt_m: self.max_alt_m = alt_m

            # Se l'aereo continua a salire sopra la quota di inizio run, era solo un livellamento provvisorio
            if alt_m > (self.buffer[0]["alt_m"] + 180):
                self.reset()
                self.last_point = point
                return

            # Riconoscimento picchiata post-lancio
            is_dive = (v_rate_fpm <= self.dive_vs_fpm) or \
                      (v_rate_fpm <= self.dive_combo_vs and (speed_kt >= self.dive_combo_spd or turn_rate > 4.0)) or \
                      (alt_m < (self.max_alt_m - 350)) or \
                      (alt_m < (self.min_alt_m - 200))

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
        if self.state == "RUN_IN" and self.last_seen > 0 and (now - self.last_seen) > 25:
            self.finalize_run()
            self.reset()
        
        # Timeout 40 minuti: aereo a terra
        if self.is_flying and self.last_seen > 0 and (now - self.last_seen) > 2400:
            self.is_flying = False
            msg = f"💤 *Tracciamento in pausa a {self.dz_name}*\nNessun segnale da {self.reg} da 40 minuti (Atterrato)."
            broadcast_telegram(self.dz_id, msg)
            broadcast_telegram(self.reg, msg)

    def finalize_run(self):
        # Esclude i punti già in picchiata ripida
        run_pts = [p for p in self.buffer if p["v_rate"] > self.dive_vs_fpm]
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
        dz_entry = next((d for d in data.get("dropzones", []) if d["id"] == self.dz_id), None)
        run_num = len([r for r in dz_entry.get("runs", []) if r.get("date") == d_str]) + 1 if dz_entry else 1

        update_dropzone_active_reg(self.dz_id, self.reg)

        # TELEGRAM: Riassunto Lancio
        model = self.fleet.get(self.reg, {}).get("model", "")
        msg = f"🪂 *Lancio Completato!*\n📍 *{self.dz_name}* — Decollo #{run_num}\n"
        msg += f"✈️ Velivolo: *{self.reg}* ({model})\n\n"
        msg += f"📏 Quota: *{exit_alt}m*\n"
        msg += f"🧭 Asse: *{avg_track}°*\n"
        msg += f"💨 Ground Speed: *{avg_speed} kt*\n"
        msg += f"⏱ Separazione 300m: *{sep_300m} s*"
        broadcast_telegram(self.dz_id, msg)
        broadcast_telegram(self.reg, msg)

        # Salvataggio file del lancio
        dz_dir = os.path.join(RUNS_DIR, self.dz_id)
        os.makedirs(dz_dir, exist_ok=True)
        f_name = f"{d_str}_run_{run_num:02d}.json"
        
        run_data = {
            "dropzone_id": self.dz_id, "dropzone": self.dz_name,
            "reg": self.reg, "model": model,
            "date": d_str, "time": t_str,
            "stats": {"altitude_m": exit_alt, "heading_deg": avg_track, "ground_speed_kt": avg_speed, "separation_sec": sep_300m, "duration_sec": duration},
            "points": [{"lat": p["lat"], "lon": p["lon"]} for p in run_pts]
        }
        with open(os.path.join(dz_dir, f_name), "w") as f: json.dump(run_data, f)
        
        update_master_index(self.dz_id, self.reg, model, self.fleet.get(self.reg, {}).get("photo", ""), f_name, d_str, t_str, duration, avg_track, avg_speed, run_num)
        push_to_github(f"Lancio {self.dz_name} #{run_num} ({self.reg})")

    def reset(self):
        self.state = "IDLE"
        self.buffer = []
        self.max_alt_m = 0

def update_master_index(dz_id, reg, model, photo, rel_file, d_str, t_str, duration, heading, speed, run_num):
    with open(INDEX_PATH, "r") as f: data = json.load(f)
    for dz in data.get("dropzones", []):
        if dz["id"] == dz_id:
            dz["active_reg"] = reg
            dz["model"] = model
            if photo: dz["photo"] = photo
            dz["runs"].insert(0, {
                "file": f"{dz_id}/{rel_file}", "reg": reg, "date": d_str, "time": t_str,
                "title": f"Decollo #{run_num}", "duration_sec": duration,
                "heading_deg": heading, "speed_kt": speed
            })
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
    
    dropzones = load_dropzones()
    fleet = load_fleet()
    ensure_master_index(dropzones, fleet)
    
    aircraft_trackers = {}
    daily_summary_sent = False
    last_heartbeat = time.time()
    
    print(f"🟢 SkyTrack Monitor avviato! Dropzone monitorate: {[d['name'] for d in dropzones]}")

    while True:
        now_time = time.time()
        dt_now = datetime.datetime.now()
        
        # Heartbeat ogni 30 minuti con elenco aerei in volo
        if (now_time - last_heartbeat) >= 1800:
            flying = [f"{t.reg}@{t.dz_name}" for t in aircraft_trackers.values() if t.is_flying]
            fly_str = f" | In volo: {flying}" if flying else " | Nessun aereo in volo"
            print(f"💓 [HEARTBEAT] Monitor attivo su {len(dropzones)} dropzone{fly_str} | Bot Telegram online.")
            last_heartbeat = now_time

        # Riassunto Giornata alle 20:30 locali
        if dt_now.hour == 20 and dt_now.minute == 30:
            if not daily_summary_sent:
                today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
                with open(INDEX_PATH, "r") as f: data = json.load(f)
                for dz in data.get("dropzones", []):
                    today_runs = [r for r in dz.get("runs", []) if r["date"] == today_str]
                    if today_runs:
                        msg = f"🌅 *Riassunto Giornata @ {dz['name']}*\nOggi completati *{len(today_runs)} decolli* registrati (Ultimo velivolo: {dz.get('active_reg')})."
                        broadcast_telegram(dz["id"], msg)
                daily_summary_sent = True
        else:
            daily_summary_sent = False

        # Scansione radar di ogni dropzone
        for dz in dropzones:
            dz_id = dz["id"]
            c_lat, c_lon = dz["center_lat"], dz["center_lon"]
            url = f"https://data-cloud.flightradar24.com/zones/fcgi/feed.js?bounds={c_lat+0.25},{c_lat-0.25},{c_lon-0.25},{c_lon+0.25}&faa=1&satellite=1&mlat=1&flarm=1&adsb=1&gnd=0&air=1&vehicles=0&estimated=1"
            try:
                r = requests.get(url, headers=HEADERS, timeout=5)
                if r.status_code == 200:
                    feed = r.json()
                    seen_regs_in_dz = set()
                    for k, val in feed.items():
                        if k in ["full_count", "version"]: continue
                        
                        raw_hex = str(val[0]).strip().upper() if len(val) > 0 else ""
                        raw_reg = val[9].strip() if len(val) > 9 and val[9] else ""
                        
                        # Risoluzione interna: prima per marca, poi per esadecimale ICAO (se presente)
                        matched_reg = None
                        if raw_reg in fleet:
                            matched_reg = raw_reg
                        elif raw_hex:
                            for reg_key, info in fleet.items():
                                if info.get("hex", "").strip().upper() == raw_hex:
                                    matched_reg = reg_key
                                    break

                        if matched_reg:
                            seen_regs_in_dz.add(matched_reg)
                            tracker_key = (dz_id, matched_reg)
                            if tracker_key not in aircraft_trackers:
                                aircraft_trackers[tracker_key] = AircraftDropzoneTracker(dz, matched_reg, fleet)
                            tracker = aircraft_trackers[tracker_key]
                            tracker.process_point(val[1], val[2], val[3] or 0, val[4] or 0, val[5] or 0, val[15] or 0)
                    
                    for (d_id, p_reg), tracker in list(aircraft_trackers.items()):
                        if d_id == dz_id and p_reg not in seen_regs_in_dz:
                            tracker.check_signal_timeout()
            except Exception:
                pass

        time.sleep(6)

if __name__ == "__main__":
    main()
