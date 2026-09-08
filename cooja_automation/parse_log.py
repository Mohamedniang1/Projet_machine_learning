#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


# ============================================================
# FORMAT DES LIGNES COOJA
# ============================================================

LINE_PATTERN = re.compile(
    r"^(?P<cooja_time_us>\d+)\s+"
    r"(?P<mote_id>\d+)\s+"
    r"\[[^\]]+\]\s+"
    r"(?P<kind>TX|RX|SUMMARY|ROOT_SUMMARY|TRAFFIC_DONE),"
    r"(?P<metrics>.*)$"
)


# ============================================================
# COLONNES : UNE LIGNE PAR RUN
# ============================================================

RUN_COLUMNS = [
    # Identification
    "run_name",
    "config_id",
    "seed",

    # Variables expérimentales
    "dio_interval_min",
    "dio_interval_min_ms",
    "dio_interval_doublings",
    "dio_interval_max_exponent",
    "dio_interval_max_ms",
    "k",
    "objective_function",
    "probing_enabled",
    "probing_interval_s",
    "tx_power_dbm",

    # Scénario fixe
    "nb_nodes",
    "nb_clients",
    "traffic_window_s",
    "measurement_windows",
    "payload_bytes",

    # Validation structurelle
    "expected_app_tx",
    "client_summary_count",
    "root_summary_count",
    "tx_log_count",
    "rx_log_count",
    "unique_rx_count",
    "traffic_done_count",

    # QoS applicative
    "pdr_global",
    "lost_packets",
    "delay_avg_ms",
    "delay_std_ms",
    "delay_min_ms",
    "delay_max_ms",
    "rssi_avg_dbm",
    "rssi_std_dbm",
    "rssi_min_dbm",
    "rssi_max_dbm",

    # PDR par fenêtre
    "pdr_window_mean",
    "pdr_window_std",
    "pdr_window_min",
    "pdr_window_max",

    # PDR / couverture par client
    "client_pdr_mean",
    "client_pdr_std",
    "client_pdr_min",
    "client_pdr_max",
    "clients_with_rx",
    "clients_without_rx",
    "clients_root_known",
    "clients_never_root_known",

    # État applicatif / RPL
    "root_known_ratio",
    "udp_sent_ratio",
    "connected_ratio",
    "etx_mean",
    "etx_std",
    "rank_mean",
    "parent_rank_mean",
    "neighbors_mean",
    "neighbors_std",

    # Energest clients : sommes sur toutes les fenêtres / tous les clients
    "client_cpu_ticks_sum",
    "client_lpm_ticks_sum",
    "client_deep_lpm_ticks_sum",
    "client_radio_tx_ticks_sum",
    "client_radio_listen_ticks_sum",
    "client_total_time_ticks_sum",

    # Energest clients : moyennes par client-fenêtre
    "client_cpu_ticks_mean",
    "client_lpm_ticks_mean",
    "client_radio_tx_ticks_mean",
    "client_radio_listen_ticks_mean",

    # Energest root : sommes sur les 36 fenêtres
    "root_cpu_ticks_sum",
    "root_lpm_ticks_sum",
    "root_deep_lpm_ticks_sum",
    "root_radio_tx_ticks_sum",
    "root_radio_listen_ticks_sum",
    "root_total_time_ticks_sum",

    # Totaux réseau utiles pour l'estimation énergétique ultérieure
    "network_cpu_ticks_sum",
    "network_lpm_ticks_sum",
    "network_deep_lpm_ticks_sum",
    "network_radio_tx_ticks_sum",
    "network_radio_listen_ticks_sum",
    "network_total_time_ticks_sum",
]


# ============================================================
# OUTILS
# ============================================================

def parse_scalar(value: str) -> Any:
    value = value.strip()

    if value == "":
        return None

    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except ValueError:
            return value

    try:
        return float(value)
    except ValueError:
        return value


def parse_metrics(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}

    for item in text.split(","):
        item = item.strip()

        if not item or "=" not in item:
            continue

        key, value = item.split("=", 1)
        result[key.strip()] = parse_scalar(value)

    return result


def safe_mean(values: list[float | int]) -> float | None:
    return statistics.fmean(values) if values else None


def safe_std(values: list[float | int]) -> float | None:
    if len(values) < 2:
        return 0.0 if len(values) == 1 else None
    return statistics.pstdev(values)


def safe_min(values: list[float | int]) -> float | int | None:
    return min(values) if values else None


def safe_max(values: list[float | int]) -> float | int | None:
    return max(values) if values else None


def sum_field(rows: list[dict[str, Any]], field: str) -> int:
    return sum(
        int(row.get(field, 0) or 0)
        for row in rows
    )


def mean_field(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [
        float(row[field])
        for row in rows
        if row.get(field) is not None
    ]
    return safe_mean(values)


# ============================================================
# CHARGEMENT CONFIG.JSON
# ============================================================

def load_config(run_dir: Path) -> dict[str, Any]:
    config_file = run_dir / "config.json"

    if not config_file.exists():
        raise FileNotFoundError(
            f"config.json introuvable : {config_file}"
        )

    with config_file.open("r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# LECTURE DU LOG
# ============================================================

def parse_testlog(log_file: Path) -> dict[str, Any]:
    if not log_file.exists():
        raise FileNotFoundError(
            f"COOJA.testlog introuvable : {log_file}"
        )

    tx_records: dict[tuple[int, int, int], dict[str, Any]] = {}
    rx_records: dict[tuple[int, int, int], dict[str, Any]] = {}

    client_summaries: dict[tuple[int, int], dict[str, Any]] = {}
    root_summaries: dict[int, dict[str, Any]] = {}
    traffic_done: dict[int, dict[str, Any]] = {}

    raw_counts = Counter()

    with log_file.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as f:

        for line in f:
            match = LINE_PATTERN.match(line.strip())

            if match is None:
                continue

            kind = match.group("kind")
            raw_counts[kind] += 1

            row = parse_metrics(match.group("metrics"))
            row["cooja_time_us"] = int(match.group("cooja_time_us"))
            row["mote_id"] = int(match.group("mote_id"))

            if kind == "TX":
                node = int(row["node"])
                seq = int(row["seq"])
                window = int(row["window"])

                tx_records[(node, seq, window)] = row

            elif kind == "RX":
                node = int(row["node"])
                seq = int(row["seq"])
                window = int(row["window"])

                rx_records[(node, seq, window)] = row

            elif kind == "SUMMARY":
                node = int(row["node"])
                window = int(row["window"])

                client_summaries[(node, window)] = row

            elif kind == "ROOT_SUMMARY":
                window = int(row["window"])

                root_summaries[window] = row

            elif kind == "TRAFFIC_DONE":
                node = int(row["node"])

                traffic_done[node] = row

    return {
        "tx_records": tx_records,
        "rx_records": rx_records,
        "client_summaries": client_summaries,
        "root_summaries": root_summaries,
        "traffic_done": traffic_done,
        "raw_counts": raw_counts,
    }


# ============================================================
# AGRÉGATION D'UN RUN
# ============================================================

def aggregate_run(
    *,
    run_dir: Path,
    config_id: int | None,
) -> dict[str, Any]:

    config = load_config(run_dir)
    parsed = parse_testlog(run_dir / "COOJA.testlog")

    params = config["parameters"]
    fixed = config["fixed_scenario"]

    run_name = str(config["run_name"])
    seed = int(config["seed"])

    nb_nodes = int(fixed["nb_nodes"])
    nb_clients = int(fixed["nb_clients"])
    traffic_window_s = int(fixed["traffic_window_s"])
    payload_bytes = int(fixed["payload_bytes"])
    measurement_duration_s = int(fixed["measurement_duration_s"])

    measurement_windows = (
        measurement_duration_s // traffic_window_s
    )

    expected_app_tx = (
        nb_clients * measurement_windows
    )

    tx_records = parsed["tx_records"]
    rx_records = parsed["rx_records"]
    client_summaries = parsed["client_summaries"]
    root_summaries = parsed["root_summaries"]
    traffic_done = parsed["traffic_done"]
    raw_counts = parsed["raw_counts"]

    # --------------------------------------------------------
    # Validation structurelle
    # --------------------------------------------------------

    expected_client_summaries = expected_app_tx
    expected_root_summaries = measurement_windows

    problems = []

    if len(client_summaries) != expected_client_summaries:
        problems.append(
            f"SUMMARY clients={len(client_summaries)} "
            f"(attendu {expected_client_summaries})"
        )

    if len(root_summaries) != expected_root_summaries:
        problems.append(
            f"ROOT_SUMMARY={len(root_summaries)} "
            f"(attendu {expected_root_summaries})"
        )

    if len(tx_records) != expected_app_tx:
        problems.append(
            f"TX uniques={len(tx_records)} "
            f"(attendu {expected_app_tx})"
        )

    if len(traffic_done) != nb_clients:
        problems.append(
            f"TRAFFIC_DONE={len(traffic_done)} "
            f"(attendu {nb_clients})"
        )

    if problems:
        raise RuntimeError(
            "Run incomplet / structure invalide : "
            + " ; ".join(problems)
        )

    # --------------------------------------------------------
    # RX uniques + délais
    # --------------------------------------------------------

    delays_ms: list[float] = []
    rssis: list[float] = []

    valid_rx_keys = set()

    for key, rx in rx_records.items():
        tx = tx_records.get(key)

        if tx is None:
            # RX sans TX correspondant : on ne l'utilise pas
            # dans le calcul du délai / PDR.
            continue

        valid_rx_keys.add(key)

        delay_us = (
            int(rx["cooja_time_us"])
            - int(tx["cooja_time_us"])
        )

        if delay_us >= 0:
            delays_ms.append(delay_us / 1000.0)

        if rx.get("rssi") is not None:
            rssis.append(float(rx["rssi"]))

    unique_rx_count = len(valid_rx_keys)

    pdr_global = (
        100.0 * unique_rx_count / expected_app_tx
        if expected_app_tx
        else None
    )

    lost_packets = expected_app_tx - unique_rx_count

    # --------------------------------------------------------
    # PDR par fenêtre
    # --------------------------------------------------------

    pdr_windows: list[float] = []

    for window in range(measurement_windows):
        root = root_summaries[window]

        rx_window = int(root.get("rx_window", 0) or 0)

        pdr_windows.append(
            100.0 * rx_window / nb_clients
        )

    # --------------------------------------------------------
    # PDR / couverture par client
    # --------------------------------------------------------

    tx_per_node = Counter()
    rx_per_node = Counter()

    root_known_per_node = Counter()

    for (node, seq, window), tx in tx_records.items():
        tx_per_node[node] += 1

        if int(tx.get("root_known", 0) or 0) == 1:
            root_known_per_node[node] += 1

    for node, seq, window in valid_rx_keys:
        rx_per_node[node] += 1

    client_pdrs = []

    clients_with_rx = 0
    clients_root_known = 0

    # Les clients sont IDs 2..36 dans le scénario actuel.
    # On évite néanmoins de dépendre du root_id en utilisant les
    # nœuds réellement présents dans les TX, ce qui reste robuste.
    client_nodes = sorted(tx_per_node.keys())

    for node in client_nodes:
        tx_count = tx_per_node[node]
        rx_count = rx_per_node[node]

        client_pdr = (
            100.0 * rx_count / tx_count
            if tx_count
            else 0.0
        )

        client_pdrs.append(client_pdr)

        if rx_count > 0:
            clients_with_rx += 1

        if root_known_per_node[node] > 0:
            clients_root_known += 1

    clients_without_rx = nb_clients - clients_with_rx
    clients_never_root_known = nb_clients - clients_root_known

    # --------------------------------------------------------
    # Ratios TX applicatifs
    # --------------------------------------------------------

    root_known_count = sum(
        int(tx.get("root_known", 0) or 0)
        for tx in tx_records.values()
    )

    udp_sent_count = sum(
        int(tx.get("udp_sent", 0) or 0)
        for tx in tx_records.values()
    )

    root_known_ratio = (
        root_known_count / expected_app_tx
    )

    udp_sent_ratio = (
        udp_sent_count / expected_app_tx
    )

    # --------------------------------------------------------
    # RPL / voisinage : tous les SUMMARY sont conservés,
    # y compris les nœuds déconnectés.
    # --------------------------------------------------------

    summary_rows = list(client_summaries.values())

    connected_values = [
        int(row.get("connected", 0) or 0)
        for row in summary_rows
    ]

    connected_ratio = (
        safe_mean(connected_values)
        if connected_values
        else None
    )

    etx_values = []
    rank_values = []
    parent_rank_values = []
    neighbor_values = []

    for row in summary_rows:
        etx_x100 = row.get("etx_x100")

        # 0 / négatif / absent = ETX invalide ou indisponible.
        if (
            etx_x100 is not None
            and float(etx_x100) > 0
        ):
            etx_values.append(
                float(etx_x100) / 100.0
            )

        rank = row.get("rank")
        if rank not in (None, 65535):
            rank_values.append(float(rank))

        parent_rank = row.get("parent_rank")
        if parent_rank not in (None, 65535):
            parent_rank_values.append(
                float(parent_rank)
            )

        neighbors = row.get("neighbors")
        if neighbors is not None:
            neighbor_values.append(
                float(neighbors)
            )

    # --------------------------------------------------------
    # Energest
    # --------------------------------------------------------

    root_rows = [
        root_summaries[w]
        for w in sorted(root_summaries)
    ]

    client_cpu = sum_field(summary_rows, "cpu_ticks")
    client_lpm = sum_field(summary_rows, "lpm_ticks")
    client_deep = sum_field(summary_rows, "deep_lpm_ticks")
    client_radio_tx = sum_field(summary_rows, "radio_tx_ticks")
    client_radio_listen = sum_field(summary_rows, "radio_listen_ticks")
    client_total_time = sum_field(summary_rows, "total_time_ticks")

    root_cpu = sum_field(root_rows, "cpu_ticks")
    root_lpm = sum_field(root_rows, "lpm_ticks")
    root_deep = sum_field(root_rows, "deep_lpm_ticks")
    root_radio_tx = sum_field(root_rows, "radio_tx_ticks")
    root_radio_listen = sum_field(root_rows, "radio_listen_ticks")
    root_total_time = sum_field(root_rows, "total_time_ticks")

    # --------------------------------------------------------
    # Ligne finale
    # --------------------------------------------------------

    row = {
        "run_name": run_name,
        "config_id": config_id,
        "seed": seed,

        "dio_interval_min": params["dio_interval_min"],
        "dio_interval_min_ms": params["dio_interval_min_ms"],
        "dio_interval_doublings": params["dio_interval_doublings"],
        "dio_interval_max_exponent": params["dio_interval_max_exponent"],
        "dio_interval_max_ms": params["dio_interval_max_ms"],
        "k": params["k"],
        "objective_function": params["objective_function"],
        "probing_enabled": int(bool(params["probing_enabled"])),
        "probing_interval_s": params["probing_interval_s"],
        "tx_power_dbm": params["tx_power_dbm"],

        "nb_nodes": nb_nodes,
        "nb_clients": nb_clients,
        "traffic_window_s": traffic_window_s,
        "measurement_windows": measurement_windows,
        "payload_bytes": payload_bytes,

        "expected_app_tx": expected_app_tx,
        "client_summary_count": len(client_summaries),
        "root_summary_count": len(root_summaries),
        "tx_log_count": raw_counts["TX"],
        "rx_log_count": raw_counts["RX"],
        "unique_rx_count": unique_rx_count,
        "traffic_done_count": len(traffic_done),

        "pdr_global": pdr_global,
        "lost_packets": lost_packets,

        "delay_avg_ms": safe_mean(delays_ms),
        "delay_std_ms": safe_std(delays_ms),
        "delay_min_ms": safe_min(delays_ms),
        "delay_max_ms": safe_max(delays_ms),

        "rssi_avg_dbm": safe_mean(rssis),
        "rssi_std_dbm": safe_std(rssis),
        "rssi_min_dbm": safe_min(rssis),
        "rssi_max_dbm": safe_max(rssis),

        "pdr_window_mean": safe_mean(pdr_windows),
        "pdr_window_std": safe_std(pdr_windows),
        "pdr_window_min": safe_min(pdr_windows),
        "pdr_window_max": safe_max(pdr_windows),

        "client_pdr_mean": safe_mean(client_pdrs),
        "client_pdr_std": safe_std(client_pdrs),
        "client_pdr_min": safe_min(client_pdrs),
        "client_pdr_max": safe_max(client_pdrs),

        "clients_with_rx": clients_with_rx,
        "clients_without_rx": clients_without_rx,
        "clients_root_known": clients_root_known,
        "clients_never_root_known": clients_never_root_known,

        "root_known_ratio": root_known_ratio,
        "udp_sent_ratio": udp_sent_ratio,
        "connected_ratio": connected_ratio,

        "etx_mean": safe_mean(etx_values),
        "etx_std": safe_std(etx_values),
        "rank_mean": safe_mean(rank_values),
        "parent_rank_mean": safe_mean(parent_rank_values),
        "neighbors_mean": safe_mean(neighbor_values),
        "neighbors_std": safe_std(neighbor_values),

        "client_cpu_ticks_sum": client_cpu,
        "client_lpm_ticks_sum": client_lpm,
        "client_deep_lpm_ticks_sum": client_deep,
        "client_radio_tx_ticks_sum": client_radio_tx,
        "client_radio_listen_ticks_sum": client_radio_listen,
        "client_total_time_ticks_sum": client_total_time,

        "client_cpu_ticks_mean": mean_field(summary_rows, "cpu_ticks"),
        "client_lpm_ticks_mean": mean_field(summary_rows, "lpm_ticks"),
        "client_radio_tx_ticks_mean": mean_field(summary_rows, "radio_tx_ticks"),
        "client_radio_listen_ticks_mean": mean_field(summary_rows, "radio_listen_ticks"),

        "root_cpu_ticks_sum": root_cpu,
        "root_lpm_ticks_sum": root_lpm,
        "root_deep_lpm_ticks_sum": root_deep,
        "root_radio_tx_ticks_sum": root_radio_tx,
        "root_radio_listen_ticks_sum": root_radio_listen,
        "root_total_time_ticks_sum": root_total_time,

        "network_cpu_ticks_sum": client_cpu + root_cpu,
        "network_lpm_ticks_sum": client_lpm + root_lpm,
        "network_deep_lpm_ticks_sum": client_deep + root_deep,
        "network_radio_tx_ticks_sum": client_radio_tx + root_radio_tx,
        "network_radio_listen_ticks_sum": (
            client_radio_listen + root_radio_listen
        ),
        "network_total_time_ticks_sum": client_total_time + root_total_time,
    }

    return row


# ============================================================
# CSV
# ============================================================

def write_run_csv(
    row: dict[str, Any],
    output_file: Path,
    *,
    append: bool,
) -> None:

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_exists = output_file.exists()
    mode = "a" if append else "w"

    with output_file.open(
        mode,
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=RUN_COLUMNS,
            extrasaction="ignore",
        )

        if not append or not file_exists:
            writer.writeheader()

        writer.writerow(row)


# ============================================================
# CLI
# ============================================================

def build_argument_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Parse un run Cooja de la nouvelle campagne "
            "Sky/RPL-Lite et produit UNE ligne CSV par run."
        )
    )

    p.add_argument(
        "--run-dir",
        type=Path,
        required=True,
        help=(
            "Dossier du run contenant config.json "
            "et COOJA.testlog."
        ),
    )

    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="CSV de sortie.",
    )

    p.add_argument(
        "--config-id",
        type=int,
        default=None,
        help="Identifiant de configuration de la campagne.",
    )

    p.add_argument(
        "--append",
        action="store_true",
        help="Ajoute la ligne au CSV existant.",
    )

    return p


def main() -> int:
    args = build_argument_parser().parse_args()

    row = aggregate_run(
        run_dir=args.run_dir,
        config_id=args.config_id,
    )

    write_run_csv(
        row,
        args.output,
        append=args.append,
    )

    print("=" * 78)
    print(f"RUN                 : {row['run_name']}")
    print(f"Seed                : {row['seed']}")
    print(f"SUMMARY clients     : {row['client_summary_count']}")
    print(f"ROOT_SUMMARY        : {row['root_summary_count']}")
    print(f"TX                  : {row['tx_log_count']}")
    print(f"RX                  : {row['unique_rx_count']}")
    print(f"PDR global          : {row['pdr_global']:.2f}%")

    if row["delay_avg_ms"] is not None:
        print(f"Delay moyen         : {row['delay_avg_ms']:.3f} ms")
    else:
        print("Delay moyen         : N/A")

    print(
        f"Clients sans RX     : "
        f"{row['clients_without_rx']}/{row['nb_clients']}"
    )
    print(
        f"Clients jamais root : "
        f"{row['clients_never_root_known']}/{row['nb_clients']}"
    )
    print(f"CSV                 : {args.output}")
    print("=" * 78)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
