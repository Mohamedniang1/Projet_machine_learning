from __future__ import annotations

import csv
import random
import traceback
from pathlib import Path

from run_cooja import run_simulation
from parse_log import parse_and_save


# ============================================================
# CHEMINS
# ============================================================

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

# RPL / Trickle
IMIN_VALUES = [8, 10, 12]

IMAX_VALUES = [16, 18, 20]

K_VALUES = [0, 5, 10]


# RPL Objective Function
OBJECTIVE_FUNCTION_VALUES = [
    "MRHOF",
    "OF0",
]


# Radio
TX_RANGE_VALUES = [
    40.0,
    50.0,
    60.0,
]


# Topologie
NB_NODES_VALUES = [
    12,
    16,
    20
]


# Application
SEND_INTERVAL_VALUES = [
    5,
    10,
    20,
]


# Répétitions stochastiques
SEEDS = [1,2,3,4,5]


# ============================================================
# CONFIGURATION DE LA CAMPAGNE
# ============================================================

# Pour test / campagne pilote
N_CONFIGURATIONS = 1000

# Temps de convergence ignoré dans parse_log.py
IGNORE_BEFORE_SECONDS = 120

# On garde seulement les nœuds connectés au DAG
CONNECTED_ONLY = True


# Seed utilisée uniquement pour générer la liste
# des configurations expérimentales.
#
# Elle rend la campagne reproductible.
EXPERIMENT_RANDOM_SEED = 2026


# ============================================================
# GÉNÉRATION DES CONFIGURATIONS
# ============================================================

def generate_random_configurations():
    """
    Génère N_CONFIGURATIONS configurations uniques.

    Une configuration contient :

        imin
        imax
        k
        tx_range
        nb_nodes
        send_interval
        objective_function

    La seed Cooja n'est PAS incluse ici :
    chaque configuration sera répétée avec plusieurs seeds.
    """

    rng = random.Random(
        EXPERIMENT_RANDOM_SEED
    )

    configurations = set()

    # --------------------------------------------------------
    # Nombre maximal théorique de configurations
    # --------------------------------------------------------

    max_possible = 0

    for imin in IMIN_VALUES:

        valid_imax = [
            value
            for value in IMAX_VALUES
            if value >= imin
        ]

        max_possible += (
            len(valid_imax)
            * len(K_VALUES)
            * len(TX_RANGE_VALUES)
            * len(NB_NODES_VALUES)
            * len(SEND_INTERVAL_VALUES)
            * len(OBJECTIVE_FUNCTION_VALUES)
        )

    if N_CONFIGURATIONS > max_possible:
        raise ValueError(
            f"N_CONFIGURATIONS={N_CONFIGURATIONS} "
            f"dépasse le nombre maximal possible "
            f"de configurations uniques : {max_possible}"
        )

    # --------------------------------------------------------
    # Tirage aléatoire contrôlé
    # --------------------------------------------------------

    while len(configurations) < N_CONFIGURATIONS:

        imin = rng.choice(
            IMIN_VALUES
        )

        valid_imax = [
            value
            for value in IMAX_VALUES
            if value >= imin
        ]

        imax = rng.choice(
            valid_imax
        )

        k = rng.choice(
            K_VALUES
        )

        tx_range = rng.choice(
            TX_RANGE_VALUES
        )

        nb_nodes = rng.choice(
            NB_NODES_VALUES
        )

        send_interval = rng.choice(
            SEND_INTERVAL_VALUES
        )

        objective_function = rng.choice(
            OBJECTIVE_FUNCTION_VALUES
        )

        configuration = (
            imin,
            imax,
            k,
            tx_range,
            nb_nodes,
            send_interval,
            objective_function,
        )

        configurations.add(
            configuration
        )

    # Pour avoir un ordre stable
    return sorted(
        configurations
    )


# ============================================================
# STATUS CSV
# ============================================================

def write_status(
    *,
    run_name: str,
    config_id: int,
    seed: int,
    imin: int,
    imax: int,
    k: int,
    tx_range: float,
    nb_nodes: int,
    send_interval: int,
    objective_function: str,
    status: str,
    rows_added: int = 0,
    error: str = "",
):
    """
    Ajoute une ligne dans experiment_status.csv.
    """

    STATUS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_exists = (
        STATUS_FILE.exists()
    )

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
        "objective_function",
        "status",
        "rows_added",
        "error",
    ]

    with STATUS_FILE.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
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
                "objective_function": objective_function,
                "status": status,
                "rows_added": rows_added,
                "error": error,
            }
        )


# ============================================================
# AFFICHAGE DES CONFIGURATIONS
# ============================================================

def print_configurations(
    configurations
):
    """
    Affiche les configurations avant lancement.
    """

    print("\n" + "=" * 80)
    print("CONFIGURATIONS EXPÉRIMENTALES")
    print("=" * 80)

    for index, config in enumerate(
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
            objective_function,
        ) = config

        print(
            f"CFG {index:03d} | "
            f"Imin={imin} | "
            f"Imax={imax} | "
            f"k={k} | "
            f"OF={objective_function} | "
            f"TX={tx_range} | "
            f"nodes={nb_nodes} | "
            f"send={send_interval}s"
        )


# ============================================================
# CAMPAGNE
# ============================================================

def run_campaign():
    """
    Lance toute la campagne expérimentale.
    """

    configurations = (
        generate_random_configurations()
    )

    total_runs = (
        len(configurations)
        * len(SEEDS)
    )

    print_configurations(
        configurations
    )

    print("\n" + "=" * 80)
    print("RÉSUMÉ DE LA CAMPAGNE")
    print("=" * 80)

    print(
        f"Configurations uniques : "
        f"{len(configurations)}"
    )

    print(
        f"Seeds par configuration : "
        f"{len(SEEDS)}"
    )

    print(
        f"Simulations prévues     : "
        f"{total_runs}"
    )

    print(
        f"Dataset final           : "
        f"{DATASET_FILE}"
    )

    print(
        f"Status                  : "
        f"{STATUS_FILE}"
    )


    # --------------------------------------------------------
    # Nettoyage des sorties anciennes
    # --------------------------------------------------------

    if DATASET_FILE.exists():
        DATASET_FILE.unlink()

    if STATUS_FILE.exists():
        STATUS_FILE.unlink()


    # --------------------------------------------------------
    # Compteurs globaux
    # --------------------------------------------------------

    run_index = 0

    success_count = 0

    failed_count = 0

    total_rows = 0


    # ========================================================
    # BOUCLE SUR LES CONFIGURATIONS
    # ========================================================

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
            objective_function,
        ) = config


        print("\n" + "#" * 80)

        print(
            f"CONFIGURATION "
            f"{config_id}/"
            f"{len(configurations)}"
        )

        print("#" * 80)

        print(
            f"Imin               : {imin}"
        )

        print(
            f"Imax               : {imax}"
        )

        print(
            f"Doublings          : {imax - imin}"
        )

        print(
            f"k                  : {k}"
        )

        print(
            f"Objective Function : "
            f"{objective_function}"
        )

        print(
            f"TX Range           : "
            f"{tx_range}"
        )

        print(
            f"Nb nodes           : "
            f"{nb_nodes}"
        )

        print(
            f"Send interval      : "
            f"{send_interval}s"
        )


        # ====================================================
        # BOUCLE SUR LES SEEDS
        # ====================================================

        for seed in SEEDS:

            run_index += 1


            # ------------------------------------------------
            # Nom du run
            # ------------------------------------------------

            run_name = (
                f"run_{run_index:04d}"
                f"_cfg_{config_id:03d}"
                f"_seed_{seed}"
                f"_{objective_function.lower()}"
            )


            print("\n" + "-" * 80)

            print(
                f"RUN "
                f"{run_index}/"
                f"{total_runs}"
            )

            print(
                f"Nom  : {run_name}"
            )

            print(
                f"Seed : {seed}"
            )

            print("-" * 80)


            try:

                # ============================================
                # 1. SIMULATION COOJA
                # ============================================

                log_file = run_simulation(
                    seed=seed,
                    imin=imin,
                    imax=imax,
                    k=k,
                    tx_range=tx_range,
                    nb_nodes=nb_nodes,
                    send_interval=send_interval,
                    objective_function=(
                        objective_function
                    ),
                    run_name=run_name,
                    clean_build=True,
                )


                # ============================================
                # 2. PARSING DU LOG
                # ============================================

                rows_added = parse_and_save(
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

                    # Cette ligne suppose que parse_log.py
                    # a été adapté pour accepter ce paramètre.
                    objective_function=(
                        objective_function
                    ),

                    ignore_before_seconds=(
                        IGNORE_BEFORE_SECONDS
                    ),

                    connected_only=(
                        CONNECTED_ONLY
                    ),

                    append=(
                        DATASET_FILE.exists()
                    ),
                )


                # ============================================
                # 3. STATUS SUCCESS
                # ============================================

                total_rows += rows_added

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
                    objective_function=(
                        objective_function
                    ),
                    status="SUCCESS",
                    rows_added=rows_added,
                )


                print(
                    f"[SUCCESS] {run_name}"
                )

                print(
                    f"[DATASET] "
                    f"{rows_added} lignes ajoutées"
                )


            except Exception as exc:

                # ============================================
                # STATUS FAILED
                # ============================================

                failed_count += 1


                print(
                    f"\n[ERREUR] "
                    f"{run_name}"
                )

                print(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )


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
                    objective_function=(
                        objective_function
                    ),
                    status="FAILED",
                    rows_added=0,
                    error=str(exc),
                )


    # ========================================================
    # RÉSUMÉ FINAL
    # ========================================================

    print("\n" + "=" * 80)
    print("CAMPAGNE TERMINÉE")
    print("=" * 80)

    print(
        f"Simulations prévues : "
        f"{total_runs}"
    )

    print(
        f"Réussies            : "
        f"{success_count}"
    )

    print(
        f"Échouées            : "
        f"{failed_count}"
    )

    print(
        f"Lignes dataset      : "
        f"{total_rows}"
    )

    print(
        f"Dataset             : "
        f"{DATASET_FILE}"
    )

    print(
        f"Status              : "
        f"{STATUS_FILE}"
    )

    if failed_count == 0:

        print(
            "\n[OK] "
            "Toutes les simulations "
            "ont été exécutées avec succès."
        )

    else:

        print(
            "\n[ATTENTION] "
            "Certaines simulations "
            "ont échoué."
        )

        print(
            "Consulte : "
            f"{STATUS_FILE}"
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    run_campaign()