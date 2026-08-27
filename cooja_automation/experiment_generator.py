#!/usr/bin/env python3

from __future__ import annotations

import csv
import itertools
import random
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

from run_cooja import run_simulation


# ============================================================
# CHEMINS
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

LOGS_DIR = SCRIPT_DIR / "logs"

DATASET_FILE = SCRIPT_DIR / "dataset.csv"

STATUS_FILE = SCRIPT_DIR / "experiment_status.csv"

PARSE_LOG_SCRIPT = SCRIPT_DIR / "parse_log.py"

TEMP_PARSE_DIR = SCRIPT_DIR / "parse_tmp"


# ============================================================
# CAMPAGNE
# ============================================================
#
# 1000 configurations × 5 seeds = 5000 simulations
#
# Pour 10 000 simulations :
#
# SEEDS = list(range(1, 11))
#
# ============================================================

N_CONFIGS = 1000

SEEDS = [1,2,3,4,5]

CONFIG_GENERATOR_SEED = 42


# ============================================================
# VALEURS EXPERIMENTALES
# ============================================================

IMIN_VALUES = [
    8,
    10,
    12,
]

IMAX_VALUES = [
    16,
    18,
    20,
]

K_VALUES = [
    0,
    5,
    10,
]

TX_RANGE_VALUES = [
    40.0,
    50.0,
    60.0,
]

NB_NODES_VALUES = [
    12,
    16,
    20,
]

SEND_INTERVAL_VALUES = [
    5,
    10,
    20,
]

OBJECTIVE_FUNCTION_VALUES = [
    "OF0",
    "MRHOF",
]


# ============================================================
# PARSING
# ============================================================

IGNORE_BEFORE_SECONDS = 120

CONNECTED_ONLY = True


# ============================================================
# NETTOYAGE
# ============================================================

DELETE_SUCCESSFUL_RUN_FILES = True

KEEP_FAILED_RUN_FILES = True


# ============================================================
# STATUS
# ============================================================

STATUS_COLUMNS = [
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


# ============================================================
# GENERATION DES CONFIGURATIONS
# ============================================================

def generate_random_configurations():
    """
    Génère N_CONFIGS configurations uniques.

    Une configuration contient :

        imin
        imax
        k
        tx_range
        nb_nodes
        send_interval
        objective_function

    La génération est reproductible grâce à
    CONFIG_GENERATOR_SEED.
    """

    all_configs = []

    for (
        imin,
        imax,
        k,
        tx_range,
        nb_nodes,
        send_interval,
        objective_function,
    ) in itertools.product(
        IMIN_VALUES,
        IMAX_VALUES,
        K_VALUES,
        TX_RANGE_VALUES,
        NB_NODES_VALUES,
        SEND_INTERVAL_VALUES,
        OBJECTIVE_FUNCTION_VALUES,
    ):

        # ----------------------------------------------------
        # Cohérence Trickle
        # ----------------------------------------------------

        if imax < imin:
            continue

        all_configs.append(
            (
                imin,
                imax,
                k,
                tx_range,
                nb_nodes,
                send_interval,
                objective_function,
            )
        )

    if N_CONFIGS > len(all_configs):

        raise ValueError(
            f"N_CONFIGS={N_CONFIGS}, mais seulement "
            f"{len(all_configs)} configurations uniques "
            f"sont possibles avec les valeurs actuelles."
        )

    rng = random.Random(
        CONFIG_GENERATOR_SEED
    )

    selected = rng.sample(
        all_configs,
        N_CONFIGS,
    )

    return selected


# ============================================================
# STATUS EXISTANT
# ============================================================

def load_status():
    """
    Charge experiment_status.csv.

    Retourne un dictionnaire :

        run_name -> status
    """

    if not STATUS_FILE.exists():
        return {}

    result = {}

    with STATUS_FILE.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as file:

        reader = csv.DictReader(
            file
        )

        for row in reader:

            run_name = row.get(
                "run_name"
            )

            status = row.get(
                "status",
                "",
            ).strip().upper()

            if run_name:
                result[run_name] = status

    return result


# ============================================================
# CREATION STATUS
# ============================================================

def ensure_status_file():
    """
    Crée experiment_status.csv s'il n'existe pas.
    """

    if STATUS_FILE.exists():
        return

    STATUS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with STATUS_FILE.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=STATUS_COLUMNS,
        )

        writer.writeheader()


# ============================================================
# AJOUT STATUS
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
    objective_function,
    status,
    rows_added,
    error,
):
    """
    Ajoute le résultat d'un run dans
    experiment_status.csv.
    """

    ensure_status_file()

    row = {
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

    with STATUS_FILE.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=STATUS_COLUMNS,
        )

        writer.writerow(
            row
        )


# ============================================================
# FORMAT DU NOM DU RUN
# ============================================================

def make_run_name(
    *,
    run_number,
    config_id,
    seed,
    objective_function,
):
    """
    Exemple :

    run_0001_cfg_001_seed_1_of0
    """

    objective_suffix = (
        objective_function
        .strip()
        .lower()
    )

    return (
        f"run_{run_number:04d}"
        f"_cfg_{config_id:03d}"
        f"_seed_{seed}"
        f"_{objective_suffix}"
    )


# ============================================================
# PARSE DU LOG DANS UN CSV TEMPORAIRE
# ============================================================

def parse_log_to_temp(
    *,
    log_file,
    run_name,
    seed,
    imin,
    imax,
    k,
    tx_range,
    nb_nodes,
    send_interval,
    objective_function,
):
    """
    Parse COOJA.testlog dans un CSV temporaire.

    On ne touche pas directement à dataset.csv
    tant que le parsing n'a pas complètement réussi.
    """

    TEMP_PARSE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_csv = (
        TEMP_PARSE_DIR
        / f"{run_name}.csv"
    )

    if temp_csv.exists():
        temp_csv.unlink()

    command = [
        sys.executable,
        str(PARSE_LOG_SCRIPT),

        "--log",
        str(log_file),

        "--output",
        str(temp_csv),

        "--run-name",
        run_name,

        "--seed",
        str(seed),

        "--imin",
        str(imin),

        "--imax",
        str(imax),

        "--k",
        str(k),

        "--tx-range",
        str(tx_range),

        "--nb-nodes",
        str(nb_nodes),

        "--send-interval",
        str(send_interval),

        "--objective-function",
        objective_function,

        "--ignore-before",
        str(IGNORE_BEFORE_SECONDS),
    ]

    if CONNECTED_ONLY:
        command.append(
            "--connected-only"
        )

    subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=True,
    )

    if not temp_csv.exists():

        raise FileNotFoundError(
            f"Le parsing n'a pas créé {temp_csv}"
        )

    return temp_csv


# ============================================================
# AJOUT AU DATASET GLOBAL
# ============================================================

def append_temp_csv_to_dataset(
    temp_csv: Path,
):
    """
    Ajoute le CSV temporaire dans dataset.csv.

    Retourne le nombre de lignes ajoutées.
    """

    with temp_csv.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as source:

        reader = csv.reader(
            source
        )

        try:
            header = next(
                reader
            )

        except StopIteration:

            raise ValueError(
                f"CSV temporaire vide : {temp_csv}"
            )

        rows = list(
            reader
        )

    if not rows:

        raise ValueError(
            f"Aucune donnée dans {temp_csv}"
        )

    # --------------------------------------------------------
    # Nouveau dataset
    # --------------------------------------------------------

    if not DATASET_FILE.exists():

        with DATASET_FILE.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as destination:

            writer = csv.writer(
                destination
            )

            writer.writerow(
                header
            )

            writer.writerows(
                rows
            )

        return len(rows)

    # --------------------------------------------------------
    # Vérification du header existant
    # --------------------------------------------------------

    with DATASET_FILE.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as existing:

        existing_reader = csv.reader(
            existing
        )

        try:
            existing_header = next(
                existing_reader
            )

        except StopIteration:

            existing_header = []

    if existing_header != header:

        raise ValueError(
            "Le schéma du CSV temporaire "
            "ne correspond pas à dataset.csv."
        )

    # --------------------------------------------------------
    # Append
    # --------------------------------------------------------

    with DATASET_FILE.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as destination:

        writer = csv.writer(
            destination
        )

        writer.writerows(
            rows
        )

    return len(rows)


# ============================================================
# NETTOYAGE TEMP PARSING
# ============================================================

def cleanup_temp_csv(
    temp_csv: Path,
):
    """
    Supprime le CSV temporaire après ajout réussi.
    """

    if temp_csv.exists():

        try:
            temp_csv.unlink()

        except OSError as exc:

            print(
                f"[WARNING] Impossible de supprimer "
                f"{temp_csv}: {exc}"
            )


# ============================================================
# NETTOYAGE DES FICHIERS COOJA
# ============================================================

def cleanup_successful_run(
    run_name: str,
):
    """
    Supprime les fichiers lourds d'une simulation
    après :

        simulation réussie
        + parsing réussi
        + ajout dataset réussi
        + status SUCCESS écrit

    Pour un run FAILED, cette fonction n'est jamais
    appelée.
    """

    if not DELETE_SUCCESSFUL_RUN_FILES:
        return

    run_directory = (
        LOGS_DIR
        / run_name
    )

    if not run_directory.exists():
        return

    files_to_delete = [
        run_directory
        / "COOJA.testlog",

        run_directory
        / "simulation.csc",
    ]

    for file_path in files_to_delete:

        if file_path.exists():

            try:
                file_path.unlink()

            except OSError as exc:

                print(
                    f"[WARNING] Impossible de supprimer "
                    f"{file_path}: {exc}"
                )

    # --------------------------------------------------------
    # Supprimer tout le dossier s'il est vide
    # --------------------------------------------------------

    try:
        run_directory.rmdir()

    except OSError:
        pass


# ============================================================
# ESPACE DISQUE
# ============================================================

def get_free_disk_gb():
    """
    Retourne l'espace libre de la partition contenant
    le projet.
    """

    usage = shutil.disk_usage(
        PROJECT_ROOT
    )

    return (
        usage.free
        / 1024
        / 1024
        / 1024
    )


def check_disk_space():
    """
    Evite de continuer si le disque est presque plein.

    IMPORTANT :
    cette sécurité évite de corrompre dataset.csv
    ou experiment_status.csv.
    """

    free_gb = get_free_disk_gb()

    if free_gb < 0.5:

        raise RuntimeError(
            f"Espace disque critique : "
            f"{free_gb:.2f} Go disponible."
        )


# ============================================================
# RESUME DATASET
# ============================================================

def count_dataset_runs():
    """
    Compte approximativement les run_name uniques
    sans charger tout dataset.csv en mémoire.
    """

    if not DATASET_FILE.exists():
        return 0

    run_names = set()

    with DATASET_FILE.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as file:

        reader = csv.DictReader(
            file
        )

        for row in reader:

            run_name = row.get(
                "run_name"
            )

            if run_name:
                run_names.add(
                    run_name
                )

    return len(run_names)


# ============================================================
# CAMPAGNE
# ============================================================

def run_campaign():
    """
    Lance toute la campagne.
    """

    print("=" * 80)
    print("CAMPAGNE COOJA")
    print("=" * 80)

    # --------------------------------------------------------
    # Configurations
    # --------------------------------------------------------

    configurations = (
        generate_random_configurations()
    )

    total_runs = (
        len(configurations)
        * len(SEEDS)
    )

    print(
        f"\nConfigurations : {len(configurations)}"
    )

    print(
        f"Seeds          : {SEEDS}"
    )

    print(
        f"Total runs     : {total_runs}"
    )

    print(
        f"Dataset        : {DATASET_FILE}"
    )

    print(
        f"Status         : {STATUS_FILE}"
    )

    print(
        f"Espace libre   : "
        f"{get_free_disk_gb():.2f} Go"
    )

    print(
        "\nNettoyage après SUCCESS : "
        f"{DELETE_SUCCESSFUL_RUN_FILES}"
    )

    # --------------------------------------------------------
    # Status existant
    # --------------------------------------------------------

    previous_status = (
        load_status()
    )

    if previous_status:

        success_count = sum(
            1
            for status
            in previous_status.values()
            if status == "SUCCESS"
        )

        print(
            f"\nReprise détectée : "
            f"{success_count} SUCCESS déjà enregistrés."
        )

    # --------------------------------------------------------
    # Compteurs
    # --------------------------------------------------------

    run_number = 0

    success = 0
    failed = 0
    skipped = 0

    total_rows_added = 0

    # --------------------------------------------------------
    # Boucle configurations
    # --------------------------------------------------------

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

        print()
        print("#" * 80)

        print(
            f"CONFIGURATION "
            f"{config_id}/{len(configurations)}"
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

        # ----------------------------------------------------
        # Les seeds sont regroupées par configuration.
        #
        # Première seed :
        #     clean_build=True
        #
        # Seeds suivantes :
        #     clean_build=False
        #
        # ----------------------------------------------------

        first_seed_to_run = True

        for seed in SEEDS:

            run_number += 1

            run_name = make_run_name(
                run_number=run_number,
                config_id=config_id,
                seed=seed,
                objective_function=(
                    objective_function
                ),
            )

            print()
            print("-" * 80)

            print(
                f"RUN {run_number}/{total_runs}"
            )

            print(
                f"Nom  : {run_name}"
            )

            print(
                f"Seed : {seed}"
            )

            print("-" * 80)

            # ------------------------------------------------
            # Reprise automatique
            # ------------------------------------------------

            old_status = previous_status.get(
                run_name
            )

            if old_status == "SUCCESS":

                print(
                    "[SKIP] Run déjà SUCCESS."
                )

                skipped += 1

                continue

            # ------------------------------------------------
            # Vérification espace
            # ------------------------------------------------

            try:

                check_disk_space()

            except Exception as exc:

                print()
                print(
                    "[STOP] Espace disque insuffisant."
                )

                print(
                    exc
                )

                print(
                    "\nLa campagne peut être relancée "
                    "plus tard : les SUCCESS seront ignorés."
                )

                return

            temp_csv = None

            try:

                # ============================================
                # 1. SIMULATION
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

                    # Première seed de la config :
                    # recompilation propre.
                    #
                    # Les suivantes utilisent le même
                    # firmware.
                    clean_build=(
                        first_seed_to_run
                    ),
                )

                first_seed_to_run = False

                # ============================================
                # 2. PARSE LOG
                # ============================================

                temp_csv = (
                    parse_log_to_temp(
                        log_file=log_file,
                        run_name=run_name,
                        seed=seed,
                        imin=imin,
                        imax=imax,
                        k=k,
                        tx_range=tx_range,
                        nb_nodes=nb_nodes,
                        send_interval=(
                            send_interval
                        ),
                        objective_function=(
                            objective_function
                        ),
                    )
                )

                # ============================================
                # 3. DATASET
                # ============================================

                rows_added = (
                    append_temp_csv_to_dataset(
                        temp_csv
                    )
                )

                # ============================================
                # 4. STATUS SUCCESS
                # ============================================

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
                    error="",
                )

                previous_status[
                    run_name
                ] = "SUCCESS"

                # ============================================
                # 5. NETTOYAGE CSV TEMP
                # ============================================

                cleanup_temp_csv(
                    temp_csv
                )

                temp_csv = None

                # ============================================
                # 6. NETTOYAGE COOJA
                # ============================================

                cleanup_successful_run(
                    run_name
                )

                # ============================================
                # RESULTAT
                # ============================================

                success += 1

                total_rows_added += (
                    rows_added
                )

                print(
                    f"[SUCCESS] {run_name}"
                )

                print(
                    f"[DATASET] "
                    f"{rows_added} lignes ajoutées"
                )

                print(
                    f"[DISQUE] "
                    f"{get_free_disk_gb():.2f} Go libres"
                )

            except KeyboardInterrupt:

                print()
                print(
                    "[STOP] Campagne interrompue "
                    "par l'utilisateur."
                )

                print(
                    "Les runs SUCCESS précédents "
                    "sont conservés."
                )

                raise

            except Exception as exc:

                failed += 1

                error_message = (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

                print()
                print(
                    f"[ERREUR] {run_name}"
                )

                print(
                    error_message
                )

                traceback.print_exc()

                # --------------------------------------------
                # Temp parse éventuel
                # --------------------------------------------

                if temp_csv is not None:

                    cleanup_temp_csv(
                        temp_csv
                    )

                # --------------------------------------------
                # FAILED dans status
                # --------------------------------------------

                try:

                    write_status(
                        run_name=run_name,
                        config_id=config_id,
                        seed=seed,
                        imin=imin,
                        imax=imax,
                        k=k,
                        tx_range=tx_range,
                        nb_nodes=nb_nodes,
                        send_interval=(
                            send_interval
                        ),
                        objective_function=(
                            objective_function
                        ),
                        status="FAILED",
                        rows_added=0,
                        error=(
                            error_message
                        ),
                    )

                    previous_status[
                        run_name
                    ] = "FAILED"

                except Exception as status_exc:

                    print(
                        "[ERREUR CRITIQUE] "
                        "Impossible d'écrire "
                        "experiment_status.csv :"
                    )

                    print(
                        status_exc
                    )

                    return

                # --------------------------------------------
                # Ne pas supprimer les fichiers FAILED
                # --------------------------------------------

                if not KEEP_FAILED_RUN_FILES:

                    cleanup_successful_run(
                        run_name
                    )

                # --------------------------------------------
                # Après une erreur on force un clean build
                # à la prochaine seed.
                # --------------------------------------------

                first_seed_to_run = True

                continue

    # ========================================================
    # FIN
    # ========================================================

    print()
    print("=" * 80)
    print("CAMPAGNE TERMINÉE")
    print("=" * 80)

    print(
        f"\nSUCCESS cette exécution : "
        f"{success}"
    )

    print(
        f"FAILED cette exécution  : "
        f"{failed}"
    )

    print(
        f"SKIPPED                 : "
        f"{skipped}"
    )

    print(
        f"Lignes ajoutées         : "
        f"{total_rows_added}"
    )

    print(
        f"Espace disque restant   : "
        f"{get_free_disk_gb():.2f} Go"
    )

    print(
        f"\nDataset : "
        f"{DATASET_FILE}"
    )

    print(
        f"Status  : "
        f"{STATUS_FILE}"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    run_campaign()