import os
import glob
import json
import datetime
import subprocess

REPO_DIR = os.path.expanduser("~/Skydiving-Skytrack")
DATA_DIR = os.path.join(REPO_DIR, "data")
RUNS_DIR = os.path.join(DATA_DIR, "runs")
INDEX_PATH = os.path.join(DATA_DIR, "index.json")
CONFIG_PATH = os.path.join(REPO_DIR, "aircraft.json")

# 1. Rimuove i file live corti (_run_) per cui esiste la versione importata (_dec_)
old_files = glob.glob(os.path.join(RUNS_DIR, "*", "*_run_*.json"))
removed = 0
for f in old_files:
    dirname = os.path.dirname(f)
    basename = os.path.basename(f)
    if "_run_" in basename:
        date_part = basename.split("_run_")[0]
        if glob.glob(os.path.join(dirname, f"{date_part}_dec_*.json")):
            try:
                os.remove(f)
                print(f"🗑️ Rimosso file duplicato corto: {basename}")
                removed += 1
            except Exception as e:
                print(f"Errore rimozione {f}: {e}")

# 2. Carica configurazione flotta
fleet = {}
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "r") as cf:
        fleet = {ac["reg"]: ac for ac in json.load(cf)}

# 3. Ricostruisce index.json da zero dai file presenti sul disco
new_aircrafts = []
for reg in sorted(fleet.keys()):
    ac_info = fleet[reg]
    ac_dir = os.path.join(RUNS_DIR, reg)
    runs_by_date = {}

    if os.path.exists(ac_dir):
        for jf in sorted(os.listdir(ac_dir)):
            if not jf.endswith(".json"):
                continue
            fpath = os.path.join(ac_dir, jf)
            try:
                with open(fpath, "r") as rf:
                    rdata = json.load(rf)
                d_str = rdata.get("date")
                t_str = rdata.get("time")
                stats = rdata.get("stats", {})
                if d_str not in runs_by_date:
                    runs_by_date[d_str] = []
                runs_by_date[d_str].append({
                    "file": f"{reg}/{jf}",
                    "date": d_str,
                    "time": t_str,
                    "duration_sec": stats.get("duration_sec", 0),
                    "heading_deg": stats.get("heading_deg", 0),
                    "speed_kt": stats.get("ground_speed_kt", 0)
                })
            except Exception as e:
                print(f"Errore lettura {fpath}: {e}")

    # Ordina cronologicamente ogni singola giornata e numera da Decollo #1 in poi
    flat_runs = []
    for d_str in sorted(runs_by_date.keys()):
        day_runs = sorted(runs_by_date[d_str], key=lambda x: x["time"])
        for idx, r in enumerate(day_runs, 1):
            r["title"] = f"Decollo #{idx}"
            flat_runs.append(r)

    # Ordina dal più recente al più vecchio per la vista nel sito web
    flat_runs.sort(key=lambda x: (x["date"], x["time"]), reverse=True)

    new_aircrafts.append({
        "reg": reg,
        "name": f"{reg} - {ac_info['name']}",
        "model": ac_info.get("model", ""),
        "runs": flat_runs
    })

master_index = {
    "aircrafts": new_aircrafts,
    "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat()
}

with open(INDEX_PATH, "w") as f:
    json.dump(master_index, f, indent=2)

print(f"✅ Indice ricostruito con successo! Eliminati {removed} file duplicati.")

try:
    subprocess.run(["git", "-C", REPO_DIR, "add", "."], check=True)
    subprocess.run(["git", "-C", REPO_DIR, "commit", "-m", "Pulizia duplicati e numerazione giornaliera decolli"], check=True)
    subprocess.run(["git", "-C", REPO_DIR, "push"], check=True)
    print("☁️ Repository GitHub aggiornato con successo!")
except Exception as e:
    print(f"Nota su Git: {e}")
