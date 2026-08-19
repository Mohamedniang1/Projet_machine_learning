from __future__ import annotations

import csv
import random
import traceback
from pathlib import Path

from run_cooja import run_simulation
from parse_log import parse_and_save


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATASET_FILE = (
    PROJECT_ROOT
    / "cooja_automation"
    / "dataset.csv"
)

STATUS_FILE = (
    PROJECT_ROOT
    / "cooja_automation"
    / "experiment_status.csv"
)


# ============================================================
# ESPACE EXPÉRIMENTAL
# ============================================================

IMIN_VALUES = [8, 10, 12]

IMAX_VALUES = [16, 18, 20]

K_VALUES = [0, 5, 10]

TX_RANGE_VALUES = [40.0, 50.0, 60.0]

NB_NODES_VALUES = [8, 12, 16]

SEND_INTERVAL_VALUES = [5, 10, 20]

SEEDS = [1, 2, 3]


# Nombre de configurations réseau différentes
N_CONFIGURATIONS = 10

IGNORE_BEFORE_SECONDS = 120
CONNECTED_ONLY = True


# Seed Python :
# permet de reproduire exactement la campagne expérimentale.
EXPERIMENT_RANDOM_SEED = 2026


# ============================================================
# GÉNÉRATION DES CONFIGURATIONS
# ============================================================

def generate_random_configurations():
    rng = random.Random(
        EXPERIMENT_RANDOM_SEED
    )

    configurations = set()

    while len(configurations) < N_CONFIGURATIONS:

        imin = rng.choice(IMIN_VALUES)

        # On interdit Imax < Imin
        valid_imax = [
            value
            for value in IMAX_VALUES
            if value >= imin
        ]

        imax = rng.choice(valid_imax)

        configuration = (
            imin,
            imax,
            rng.choice(K_VALUES),
            rng.choice(TX_RANGE_VALUES),
            rng.choice(NB_NODES_VALUES),
            rng.choice(SEND_INTERVAL_VALUES),
        )

        configurations.add(configuration)

    return list(configurations)


# ============================================================
# STATUS
# ============================================================

def write_status(
    *,
    run_name,
    config_id,
    seed,
    imin,
    imax,
    k,
    tx_range,
    nb_nodes,
    send_interval,
    status,
    rows_added=0,
    error="",
):

    file_exists = STATUS_FILE.exists()

    with STATUS_FILE.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as f:

        fieldnames = [
            "run_name",
            "config_id",
            "seed",
            "imin",
            "imax",
            "k",
            "tx_range",
            "nb_nodes",
            "send_interval",
            "status",
            "rows_added",
            "error",
        ]

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )

        if (
            not file_exists
            or STATUS_FILE.stat().st_size == 0
        ):
            writer.writeheader()

        writer.writerow(
            {
                "run_name": run_name,
                "config_id": config_id,
                "seed": seed,
                "imin": imin,
                "imax": imax,
                "k": k,
                "tx_range": tx_range,
                "nb_nodes": nb_nodes,
                "send_interval": send_interval,
                "status": status,
                "rows_added": rows_added,
                "error": error,
            }
        )


# ============================================================
# CAMPAGNE
# ============================================================

def run_campaign():

    configurations = (
        generate_random_configurations()
    )

    total_runs = (
        len(configurations)
        * len(SEEDS)
    )

    print(
        f"\nConfigurations : "
        f"{len(configurations)}"
    )

    print(
        f"Seeds/config   : "
        f"{len(SEEDS)}"
    )

    print(
        f"Simulations    : "
        f"{total_runs}"
    )

    if DATASET_FILE.exists():
        DATASET_FILE.unlink()

    if STATUS_FILE.exists():
        STATUS_FILE.unlink()

    run_index = 0
    success_count = 0
    failed_count = 0
    total_rows = 0

    for config_id, config in enumerate(
        configurations,
        start=1,
    ):

        (
            imin,
            imax,
            k,
            tx_range,
            nb_nodes,
            send_interval,
        ) = config

        print("\n" + "#" * 75)

        print(
            f"CONFIGURATION {config_id}/"
            f"{len(configurations)}"
        )

        print(
            f"Imin={imin}, "
            f"Imax={imax}, "
            f"k={k}, "
            f"tx_range={tx_range}, "
            f"nodes={nb_nodes}, "
            f"send={send_interval}"
        )

        print("#" * 75)

        for seed in SEEDS:

            run_index += 1

            run_name = (
                f"run_{run_index:04d}"
                f"_cfg_{config_id:03d}"
                f"_seed_{seed}"
            )

            try:

                log_file = run_simulation(
                    seed=seed,
                    imin=imin,
                    imax=imax,
                    k=k,
                    tx_range=tx_range,
                    nb_nodes=nb_nodes,
                    send_interval=send_interval,
                    run_name=run_name,
                    clean_build=True,
                )

                rows = parse_and_save(
                    log_file=log_file,
                    output_file=DATASET_FILE,
                    run_name=run_name,
                    seed=seed,
                    imin=imin,
                    imax=imax,
                    k=k,
                    tx_range=tx_range,
                    nb_nodes=nb_nodes,
                    send_interval=send_interval,
                    ignore_before_seconds=(
                        IGNORE_BEFORE_SECONDS
                    ),
                    connected_only=CONNECTED_ONLY,
                    append=DATASET_FILE.exists(),
                )

                total_rows += rows
                success_count += 1

                write_status(
                    run_name=run_name,
                    config_id=config_id,
                    seed=seed,
                    imin=imin,
                    imax=imax,
                    k=k,
                    tx_range=tx_range,
                    nb_nodes=nb_nodes,
                    send_interval=send_interval,
                    status="SUCCESS",
                    rows_added=rows,
                )

            except Exception as exc:

                failed_count += 1

                print(
                    f"\n[ERREUR] {run_name}"
                )

                print(exc)

                traceback.print_exc()

                write_status(
                    run_name=run_name,
                    config_id=config_id,
                    seed=seed,
                    imin=imin,
                    imax=imax,
                    k=k,
                    tx_range=tx_range,
                    nb_nodes=nb_nodes,
                    send_interval=send_interval,
                    status="FAILED",
                    error=str(exc),
                )

    print("\n" + "=" * 75)
    print("CAMPAGNE TERMINÉE")
    print("=" * 75)

    print(
        f"Simulations prévues : {total_runs}"
    )

    print(
        f"Réussies            : {success_count}"
    )

    print(
        f"Échouées            : {failed_count}"
    )

    print(
        f"Lignes dataset      : {total_rows}"
    )

    print(
        f"Dataset             : {DATASET_FILE}"
    )


if __name__ == "__main__":
    run_campaign()