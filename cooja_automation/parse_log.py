import re
import os
import pandas as pd
import config

# --- ID du mote racine tel que défini dans le .csc (server_type -> id=1) ---
# Rendu configurable ici plutôt qu'en dur dans la regex.
SERVER_MOTE_ID = getattr(config, "SERVER_MOTE_ID", 1)

# Seuil de sécurité pour détecter un delay manifestement corrompu.
# Ajuste selon la durée réelle de tes paquets (778ms max observé jusqu'ici).
MAX_PLAUSIBLE_DELAY_MS = 60_000


def parse_cooja_log():
    log_path = config.LOG_FILE_PATH
    output_csv = config.DATASET_CSV_PATH

    if not os.path.exists(log_path):
        print(f"[!] Fichier de log introuvable : {log_path}")
        return

    parsed_data = []

    # --- Regex mise à jour pour le nouveau format C ---
    # Ligne brute attendue : "<sim_time_us> <mote_id> [INFO: App   ] METRIC,node,seq,rssi,pdr,delay"
    metric_pattern = re.compile(
        r'(\d+)\s+' + str(SERVER_MOTE_ID) + r'\s+'
        r'\[INFO:\s+App\s+\]\s+'
        r'METRIC,(\d+),(\d+),(-?\d+),(\d+),(\d+)'
    )

    print(f"[*] Analyse du fichier de log : {log_path}")

    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            match = metric_pattern.search(line)
            if not match:
                continue

            sim_time_us = int(match.group(1))   # temps de simulation Cooja, en microsecondes
            node_id = int(match.group(2))
            seq_no = int(match.group(3))
            rssi = int(match.group(4))
            pdr_x1000 = int(match.group(5))      # PDR cumulatif calculé côté C, en pour-mille
            delay_ms = int(match.group(6))

            # Nettoyage des valeurs de delay manifestement corrompues
            # (utile en filet de sécurité, même après la correction du
            # sscanf côté C qui causait la plupart de ces valeurs aberrantes)
            if delay_ms > MAX_PLAUSIBLE_DELAY_MS:
                delay_ms = None

            parsed_data.append({
                'timestamp_us': sim_time_us,
                'node_id': node_id,
                'seq_no': seq_no,
                'rssi_dbm': rssi,
                'pdr_percent': pdr_x1000 / 10.0,   # conversion pour-mille -> pourcentage
                'delay_ms': delay_ms,
            })

    df = pd.DataFrame(parsed_data)

    if df.empty:
        print("[!] Aucune métrique extraite des logs. "
              "Vérifie que la regex correspond bien au format imprimé par udp-server.c "
              "(teste `grep METRIC ton_fichier.log` pour voir le format brut réel).")
        return

    df.to_csv(output_csv, index=False)
    print(f"[+] Dataset généré avec succès ({len(df)} échantillons) : {output_csv}")

    # Petit résumé utile pour repérer rapidement un problème de variance
    print("\n--- Aperçu rapide ---")
    print(f"Nœuds détectés : {sorted(df.node_id.unique())}")
    print(f"PDR : min={df.pdr_percent.min():.1f}%  max={df.pdr_percent.max():.1f}%  "
          f"(si min==max==100%, vérifie success_ratio_tx/rx dans le .csc)")
    print(f"Delay manquants : {df.delay_ms.isna().sum()} / {len(df)}")


if __name__ == "__main__":
    parse_cooja_log()