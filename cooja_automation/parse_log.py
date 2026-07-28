import re
import os
import pandas as pd
import config

def parse_cooja_log():
    log_path = config.LOG_FILE_PATH
    output_csv = config.DATASET_CSV_PATH

    if not os.path.exists(log_path):
        print(f"[!] Fichier de log introuvable : {log_path}")
        return

    canary_found = False
    parsed_data = []

    # Regex mise à jour pour capturer les logs METRIC émis par les clients
    metric_pattern = re.compile(
        r'(\d+)\s+(\d+)\s+\[INFO:\s+App\s+\]\s+METRIC,node=(\d+),seq=(\d+),rssi=(-\d+|\d+),delay=(\d+)'
    )

    print(f"[*] Analyse du fichier de log : {log_path}")

    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if "[CANARY_v2.0" in line:
                canary_found = True

            match = metric_pattern.search(line)
            if match:
                sim_time_ms = int(match.group(1)) // 1000  # us en ms
                node_id = int(match.group(3))
                seq_no = int(match.group(4))
                rssi = int(match.group(5))
                delay_ms = int(match.group(6))

                parsed_data.append({
                    'timestamp_ms': sim_time_ms,
                    'node_id': node_id,
                    'seq_no': seq_no,
                    'rssi_dbm': rssi,
                    'delay_ms': delay_ms
                })

    if canary_found:
        print("[+] VERIFICATION CANARI : Le nouveau code C v2.0 a bien été exécuté par Cooja !")
    else:
        print("[!] ATTENTION CANARI NON TROUVÉ : Cooja a peut-être utilisé un binaire obsolète.")

    df = pd.DataFrame(parsed_data)

    if df.empty:
        print("[!] Aucune métrique extraite des logs.")
        return

    # Calcul dynamique du PDR réel par nœud (Paquets reçus / Séquence maximale)
    node_stats = df.groupby('node_id').agg(
        total_recus=('seq_no', 'count'),
        seq_max=('seq_no', 'max'),
        seq_min=('seq_no', 'min')
    )
    node_stats['pdr_percent'] = (node_stats['total_recus'] / (node_stats['seq_max'] - node_stats['seq_min'] + 1)) * 100.0

    df = df.merge(node_stats[['pdr_percent']], on='node_id', how='left')
    df.to_csv(output_csv, index=False)

    print(f"[+] Dataset généré avec succès ({len(df)} échantillons) : {output_csv}")

if __name__ == "__main__":
    parse_cooja_log()