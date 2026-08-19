from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Any


# ============================================================
# CHEMINS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_LOG_FILE = (
    PROJECT_ROOT
    / "cooja_automation"
    / "logs"
    / "test_new_parameters"
    / "COOJA.testlog"
)

DEFAULT_OUTPUT_FILE = (
    PROJECT_ROOT
    / "cooja_automation"
    / "dataset.csv"
)


# ============================================================
# FORMAT DES LIGNES SUMMARY
# ============================================================

# Exemple :
#
# 60073000 8 [INFO: App       ] SUMMARY,node=8,time=60,...
#
SUMMARY_PATTERN = re.compile(
    r"^(?P<cooja_time>\d+)\s+"
    r"(?P<mote_id>\d+)\s+"
    r"\[[^\]]+\]\s+"
    r"SUMMARY,(?P<metrics>.+)$"
)


# ============================================================
# CHAMPS ENTIERS
# ============================================================

INTEGER_FIELDS = {
    "cooja_time",
    "mote_id",

    "node",
    "time",

    "tx_total",
    "rx_total",
    "dup_total",

    "pdr_global_x100",

    "tx_window",
    "rx_window",
    "dup_window",

    "pdr_window_x100",

    "delay_avg_ms",
    "delay_min_ms",
    "delay_max_ms",

    "rssi_avg",

    "etx_x100",

    "rank",
    "parent_rank",
    "parent_id",
    "neighbors",

    "cpu_ticks",
    "lpm_ticks",
    "deep_lpm_ticks",

    "radio_tx_ticks",
    "radio_listen_ticks",

    "total_time_ticks",

    # Anciennes versions du client
    "energy_ticks",

    # Version plus récente
    "activity_ticks",
}


# ============================================================
# COLONNES DU DATASET
# ============================================================

CSV_COLUMNS = [

    # --------------------------------------------------------
    # IDENTIFICATION DE L'EXPÉRIENCE
    # --------------------------------------------------------

    "run_name",

    # --------------------------------------------------------
    # PARAMÈTRES CONTRÔLÉS
    # --------------------------------------------------------

    "seed",

    "imin",
    "imax",
    "k",

    "tx_range",

    "nb_nodes",

    "send_interval",

    # --------------------------------------------------------
    # INFORMATIONS COOJA
    # --------------------------------------------------------

    "cooja_time",
    "mote_id",

    # --------------------------------------------------------
    # INFORMATIONS DU NŒUD
    # --------------------------------------------------------

    "node",
    "time",

    # --------------------------------------------------------
    # PACKETS / PDR
    # --------------------------------------------------------

    "tx_total",
    "rx_total",
    "dup_total",

    "pdr_global",

    "tx_window",
    "rx_window",
    "dup_window",

    "pdr_window",

    # --------------------------------------------------------
    # DELAY
    # --------------------------------------------------------

    "delay_avg_ms",
    "delay_min_ms",
    "delay_max_ms",

    # --------------------------------------------------------
    # RADIO / RPL
    # --------------------------------------------------------

    "rssi_avg",
    "etx",

    "rank",
    "parent_rank",
    "parent_id",

    "neighbors",

    # --------------------------------------------------------
    # ENERGEST
    # --------------------------------------------------------

    "cpu_ticks",
    "lpm_ticks",
    "deep_lpm_ticks",

    "radio_tx_ticks",
    "radio_listen_ticks",

    "total_time_ticks",

    # On garde les deux pour compatibilité.
    "energy_ticks",
    "activity_ticks",

    # --------------------------------------------------------
    # ÉTAT DU NŒUD
    # --------------------------------------------------------

    "connected",
]


# ============================================================
# PARSING DES COUPLES CLE=VALEUR
# ============================================================

def parse_key_value_metrics(
    metrics_text: str,
) -> dict[str, Any]:
    """
    Transforme :

        node=8,time=60,tx_total=3,...

    en :

        {
            "node": 8,
            "time": 60,
            "tx_total": 3,
            ...
        }
    """

    metrics: dict[str, Any] = {}

    items = metrics_text.strip().split(",")

    for item in items:

        item = item.strip()

        if not item:
            continue

        if "=" not in item:
            continue

        key, value = item.split("=", 1)

        key = key.strip()
        value = value.strip()

        if key in INTEGER_FIELDS:

            try:
                metrics[key] = int(value)

            except ValueError:

                print(
                    f"[WARNING] Impossible de convertir "
                    f"{key}={value} en entier."
                )

                metrics[key] = None

        else:

            metrics[key] = value

    return metrics


# ============================================================
# PARSING D'UNE LIGNE SUMMARY
# ============================================================

def parse_summary_line(
    line: str,
) -> dict[str, Any] | None:
    """
    Analyse une ligne de COOJA.testlog.

    Retourne :
        dictionnaire contenant les métriques

    ou :
        None si la ligne n'est pas une ligne SUMMARY.
    """

    line = line.strip()

    match = SUMMARY_PATTERN.match(line)

    if match is None:
        return None

    metrics_text = match.group("metrics")

    row = parse_key_value_metrics(
        metrics_text
    )

    # --------------------------------------------------------
    # Informations fournies par Cooja
    # --------------------------------------------------------

    row["cooja_time"] = int(
        match.group("cooja_time")
    )

    row["mote_id"] = int(
        match.group("mote_id")
    )

    # --------------------------------------------------------
    # PDR
    # --------------------------------------------------------

    pdr_global_x100 = row.pop(
        "pdr_global_x100",
        None,
    )

    pdr_window_x100 = row.pop(
        "pdr_window_x100",
        None,
    )

    # Dans udp-client :
    #
    # 10000 = 100 %
    # 9750  = 97.50 %
    #

    if pdr_global_x100 is not None:

        row["pdr_global"] = (
            pdr_global_x100 / 100.0
        )

    else:

        row["pdr_global"] = None

    if pdr_window_x100 is not None:

        row["pdr_window"] = (
            pdr_window_x100 / 100.0
        )

    else:

        row["pdr_window"] = None

    # --------------------------------------------------------
    # ETX
    # --------------------------------------------------------

    etx_x100 = row.pop(
        "etx_x100",
        None,
    )

    # Exemple :
    #
    # 149 -> 1.49
    #

    if etx_x100 not in (None, 0):

        row["etx"] = (
            etx_x100 / 100.0
        )

    else:

        row["etx"] = None

    # --------------------------------------------------------
    # CONNECTIVITÉ RPL
    # --------------------------------------------------------

    rank = row.get("rank")
    parent_id = row.get("parent_id")

    # Dans notre udp-client :
    #
    # 65535 = valeur invalide
    #

    connected = (
        rank not in (None, 65535)
        and
        parent_id not in (None, 65535)
    )

    row["connected"] = int(
        connected
    )

    return row


# ============================================================
# LECTURE DU FICHIER LOG
# ============================================================

def parse_log_file(
    log_file: Path,
    *,
    run_name: str = "",

    seed: int | None = None,

    imin: int | None = None,
    imax: int | None = None,
    k: int | None = None,

    tx_range: float | None = None,

    nb_nodes: int | None = None,

    send_interval: int | None = None,

    ignore_before_seconds: int = 0,

    connected_only: bool = False,

) -> list[dict[str, Any]]:
    """
    Lit COOJA.testlog et extrait les lignes SUMMARY.

    Les paramètres expérimentaux sont ajoutés à chaque
    observation.

    Exemple :

        seed
        imin
        imax
        k
        tx_range
        nb_nodes
        send_interval

    Cela permet de savoir quelle configuration a produit
    chaque mesure réseau.
    """

    if not log_file.exists():

        raise FileNotFoundError(
            f"Fichier log introuvable : {log_file}"
        )

    rows: list[dict[str, Any]] = []

    summary_seen = 0
    ignored_convergence = 0
    ignored_disconnected = 0

    with log_file.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as file:

        for line in file:

            row = parse_summary_line(
                line
            )

            if row is None:
                continue

            summary_seen += 1

            # ------------------------------------------------
            # CONVERGENCE
            # ------------------------------------------------

            simulation_time = row.get(
                "time",
                0,
            )

            if simulation_time is None:
                simulation_time = 0

            if (
                simulation_time
                < ignore_before_seconds
            ):

                ignored_convergence += 1
                continue

            # ------------------------------------------------
            # CONNECTIVITÉ
            # ------------------------------------------------

            if (
                connected_only
                and
                row["connected"] == 0
            ):

                ignored_disconnected += 1
                continue

            # ------------------------------------------------
            # PARAMÈTRES DE L'EXPÉRIENCE
            # ------------------------------------------------

            row["run_name"] = (
                run_name
                if run_name
                else log_file.parent.name
            )

            row["seed"] = seed

            row["imin"] = imin
            row["imax"] = imax
            row["k"] = k

            row["tx_range"] = tx_range

            row["nb_nodes"] = nb_nodes

            row["send_interval"] = (
                send_interval
            )

            rows.append(
                row
            )

    print(
        f"[PARSE] SUMMARY trouvés      : "
        f"{summary_seen}"
    )

    print(
        f"[PARSE] Ignorés convergence  : "
        f"{ignored_convergence}"
    )

    print(
        f"[PARSE] Ignorés non connectés : "
        f"{ignored_disconnected}"
    )

    print(
        f"[PARSE] Conservés             : "
        f"{len(rows)}"
    )

    return rows


# ============================================================
# ÉCRITURE CSV
# ============================================================

def write_rows_to_csv(
    rows: list[dict[str, Any]],
    output_file: Path,
    *,
    append: bool = False,
) -> None:
    """
    Enregistre les observations dans dataset.csv.

    append=False :
        remplace le fichier.

    append=True :
        ajoute les nouvelles observations.
    """

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_exists = (
        output_file.exists()
    )

    if append:
        mode = "a"
    else:
        mode = "w"

    with output_file.open(
        mode,
        newline="",
        encoding="utf-8",
    ) as csv_file:

        writer = csv.DictWriter(
            csv_file,
            fieldnames=CSV_COLUMNS,
            extrasaction="ignore",
        )

        # Écrire l'entête uniquement si nécessaire.

        must_write_header = (
            not append
            or not file_exists
            or output_file.stat().st_size == 0
        )

        if must_write_header:
            writer.writeheader()

        for row in rows:
            writer.writerow(row)


# ============================================================
# PARSE + SAUVEGARDE
# ============================================================

def parse_and_save(
    *,
    log_file: Path,
    output_file: Path,

    run_name: str = "",

    seed: int | None = None,

    imin: int | None = None,
    imax: int | None = None,
    k: int | None = None,

    tx_range: float | None = None,

    nb_nodes: int | None = None,

    send_interval: int | None = None,

    ignore_before_seconds: int = 0,

    connected_only: bool = False,

    append: bool = False,

) -> int:
    """
    Fonction utilisée par experiment_generator.py.

    Pipeline :

        COOJA.testlog
              ↓
        parse_log_file()
              ↓
        lignes Python
              ↓
        dataset.csv

    Retourne le nombre de lignes ajoutées.
    """

    rows = parse_log_file(
        log_file,

        run_name=run_name,

        seed=seed,

        imin=imin,
        imax=imax,
        k=k,

        tx_range=tx_range,

        nb_nodes=nb_nodes,

        send_interval=send_interval,

        ignore_before_seconds=(
            ignore_before_seconds
        ),

        connected_only=connected_only,
    )

    if not rows:

        print(
            "[WARNING] "
            "Aucune ligne SUMMARY exploitable."
        )

        return 0

    write_rows_to_csv(
        rows,
        output_file,
        append=append,
    )

    print(
        f"[OK] {len(rows)} lignes "
        f"ajoutées dans :"
    )

    print(
        f"     {output_file}"
    )

    return len(rows)


# ============================================================
# ARGUMENTS TERMINAL
# ============================================================

def build_argument_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        description=(
            "Extraction des métriques SUMMARY "
            "d'une simulation Cooja vers CSV."
        )
    )

    parser.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG_FILE,
        help="Chemin vers COOJA.testlog",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
        help="Fichier CSV de sortie",
    )

    parser.add_argument(
        "--run-name",
        default="",
    )

    parser.add_argument(
        "--seed",
        type=int,
    )

    parser.add_argument(
        "--imin",
        type=int,
    )

    parser.add_argument(
        "--imax",
        type=int,
    )

    parser.add_argument(
        "--k",
        type=int,
    )

    parser.add_argument(
        "--tx-range",
        type=float,
    )

    parser.add_argument(
        "--nb-nodes",
        type=int,
    )

    parser.add_argument(
        "--send-interval",
        type=int,
    )

    parser.add_argument(
        "--ignore-before",
        type=int,
        default=0,
        help=(
            "Ignorer les mesures avant ce temps "
            "simulé en secondes."
        ),
    )

    parser.add_argument(
        "--connected-only",
        action="store_true",
        help=(
            "Conserver uniquement les nœuds "
            "ayant rejoint le DAG RPL."
        ),
    )

    parser.add_argument(
        "--append",
        action="store_true",
        help=(
            "Ajouter au dataset existant "
            "au lieu de l'écraser."
        ),
    )

    return parser


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    parser = build_argument_parser()

    args = parser.parse_args()

    parse_and_save(

        log_file=args.log,

        output_file=args.output,

        run_name=args.run_name,

        seed=args.seed,

        imin=args.imin,
        imax=args.imax,
        k=args.k,

        tx_range=args.tx_range,

        nb_nodes=args.nb_nodes,

        send_interval=args.send_interval,

        ignore_before_seconds=(
            args.ignore_before
        ),

        connected_only=(
            args.connected_only
        ),

        append=args.append,
    )


if __name__ == "__main__":
    main()