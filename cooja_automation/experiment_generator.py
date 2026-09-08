#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import itertools
import random
import re
import shlex
import shutil
import subprocess
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from parse_log import aggregate_run, write_run_csv
from run_cooja import (
    BASE_CSC_FILE,
    CONTIKI_DIR,
    COOJA_DIR,
    PROJECT_CONF_FILE,
    RPL_UDP_DIR,
    build_metadata,
    compile_firmwares,
    inspect_testlog,
    prepare_run_directory,
    validate_base_csc,
    validate_parameters,
    write_json,
    write_project_conf,
)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
LOGS_DIR = SCRIPT_DIR / "logs"

DEFAULT_WORKERS = 5
DEFAULT_MIN_FREE_DISK_GB = 2.0
DEFAULT_MIN_AVAILABLE_RAM_GB = 2.0

# ============================================================
# CAMPAGNE / DATASET - VERSION AUTONOME
# ============================================================

DATASET_FILE = SCRIPT_DIR / "dataset_runs_new.csv"
STATUS_FILE = SCRIPT_DIR / "experiment_status_new.csv"
MANIFEST_FILE = SCRIPT_DIR / "campaign_manifest.csv"

DEFAULT_N_CONFIGS = 10
DEFAULT_SEEDS = [1,2]
CONFIG_GENERATOR_SEED = 42

DIO_INTERVAL_MIN_VALUES = [3, 6, 9, 12]
DIO_INTERVAL_DOUBLINGS_VALUES = [4, 8, 12]
K_VALUES = [0, 1, 5, 10]
OBJECTIVE_FUNCTION_VALUES = ["OF0", "MRHOF"]

PROBING_CHOICES = [
    (False, None),
    (True, 30),
    (True, 90),
    (True, 180),
]

TX_POWER_DBM_VALUES = [-25, -15, -7, 0]
MAX_DIO_EXPONENT = 24

DELETE_SUCCESSFUL_RUN_FILES = True

FILES_TO_DELETE_AFTER_SUCCESS = [
    "COOJA.testlog",
    "simulation.csc",
    "compile.log",
    "cooja_console.log",
    "project-conf.h",
    "cooja_command.txt",
]

STATUS_COLUMNS = [
    "run_name",
    "config_id",
    "seed",
    "dio_interval_min",
    "dio_interval_doublings",
    "dio_interval_max_exponent",
    "k",
    "objective_function",
    "probing_enabled",
    "probing_interval_s",
    "tx_power_dbm",
    "status",
    "error",
]

MANIFEST_COLUMNS = [
    "config_id",
    "dio_interval_min",
    "dio_interval_doublings",
    "dio_interval_max_exponent",
    "k",
    "objective_function",
    "probing_enabled",
    "probing_interval_s",
    "tx_power_dbm",
]


def generate_all_valid_configurations() -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []

    for (
        dio_interval_min,
        dio_interval_doublings,
        k,
        objective_function,
        probing_choice,
        tx_power_dbm,
    ) in itertools.product(
        DIO_INTERVAL_MIN_VALUES,
        DIO_INTERVAL_DOUBLINGS_VALUES,
        K_VALUES,
        OBJECTIVE_FUNCTION_VALUES,
        PROBING_CHOICES,
        TX_POWER_DBM_VALUES,
    ):
        probing_enabled, probing_interval_s = probing_choice
        max_exponent = dio_interval_min + dio_interval_doublings

        if max_exponent > MAX_DIO_EXPONENT:
            continue

        configs.append(
            {
                "dio_interval_min": dio_interval_min,
                "dio_interval_doublings": dio_interval_doublings,
                "dio_interval_max_exponent": max_exponent,
                "k": k,
                "objective_function": objective_function,
                "probing_enabled": probing_enabled,
                "probing_interval_s": probing_interval_s,
                "tx_power_dbm": tx_power_dbm,
            }
        )

    return configs


def sample_configurations(n_configs: int) -> list[dict[str, Any]]:
    if n_configs <= 0:
        raise ValueError("n_configs doit être > 0.")

    all_configs = generate_all_valid_configurations()

    if n_configs > len(all_configs):
        raise ValueError(
            f"n_configs={n_configs}, mais seulement "
            f"{len(all_configs)} configurations valides existent."
        )

    rng = random.Random(CONFIG_GENERATOR_SEED)
    return rng.sample(all_configs, n_configs)


def write_manifest(configurations: list[dict[str, Any]]) -> None:
    with MANIFEST_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()

        for config_id, config in enumerate(configurations, start=1):
            writer.writerow({"config_id": config_id, **config})


def ensure_status_file() -> None:
    if STATUS_FILE.exists():
        return

    with STATUS_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=STATUS_COLUMNS)
        writer.writeheader()


def load_dataset_run_names() -> set[str]:
    if not DATASET_FILE.exists():
        return set()

    with DATASET_FILE.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {
            str(row["run_name"]).strip()
            for row in reader
            if row.get("run_name")
        }


def write_status(
    *,
    run_name: str,
    config_id: int,
    seed: int,
    config: dict[str, Any],
    status: str,
    error: str = "",
) -> None:
    ensure_status_file()

    row = {
        "run_name": run_name,
        "config_id": config_id,
        "seed": seed,
        **config,
        "status": status,
        "error": error,
    }

    with STATUS_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=STATUS_COLUMNS)
        writer.writerow(row)


def make_run_name(
    *,
    run_number: int,
    config_id: int,
    seed: int,
    objective_function: str,
) -> str:
    of_suffix = objective_function.strip().lower()

    return (
        f"run_{run_number:05d}"
        f"_cfg_{config_id:04d}"
        f"_seed_{seed}"
        f"_{of_suffix}"
    )


def cleanup_successful_run(run_dir: Path) -> None:
    if not DELETE_SUCCESSFUL_RUN_FILES:
        return

    for filename in FILES_TO_DELETE_AFTER_SUCCESS:
        path = run_dir / filename

        if not path.exists():
            continue

        try:
            path.unlink()
        except OSError as exc:
            print(
                f"[WARNING] Impossible de supprimer {path}: {exc}"
            )



def get_free_disk_gb() -> float:
    return shutil.disk_usage(PROJECT_ROOT).free / (1024 ** 3)


def get_available_ram_gb() -> float:
    p = Path("/proc/meminfo")
    if not p.exists():
        return float("inf")
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / (1024 ** 2)
    return float("inf")


def get_swap_used_gb() -> float:
    p = Path("/proc/meminfo")
    if not p.exists():
        return 0.0
    vals: dict[str, int] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        parts = line.replace(":", "").split()
        if len(parts) >= 2 and parts[0] in {"SwapTotal", "SwapFree"}:
            vals[parts[0]] = int(parts[1])
    return max(0, vals.get("SwapTotal", 0) - vals.get("SwapFree", 0)) / (1024 ** 2)


def print_resources(prefix: str = "[RESSOURCES]") -> None:
    print(
        f"{prefix} RAM dispo={get_available_ram_gb():.2f} Go | "
        f"swap utilisé={get_swap_used_gb():.2f} Go | "
        f"disque libre={get_free_disk_gb():.2f} Go"
    )


def patch_csc_firmware_paths(
    *,
    csc_file: Path,
    server_firmware: Path,
    client_firmware: Path,
) -> None:
    """Fait pointer le .csc vers les copies privées du run."""
    text = csc_file.read_text(encoding="utf-8")

    server_path = xml_escape(str(server_firmware.resolve()))
    client_path = xml_escape(str(client_firmware.resolve()))

    text, n_server = re.subn(
        r"<firmware>[^<]*udp-server\.sky</firmware>",
        f"<firmware>{server_path}</firmware>",
        text,
        count=1,
    )
    text, n_client = re.subn(
        r"<firmware>[^<]*udp-client\.sky</firmware>",
        f"<firmware>{client_path}</firmware>",
        text,
        count=1,
    )

    if n_server != 1 or n_client != 1:
        raise RuntimeError(
            "Impossible de figer les chemins firmware dans le .csc "
            f"(server={n_server}, client={n_client})."
        )

    csc_file.write_text(text, encoding="utf-8")


def prepare_frozen_run(
    *,
    run_name: str,
    seed: int,
    config: dict[str, Any],
) -> Path:
    """
    Partie volontairement SEQUENTIELLE : project-conf + compilation partagée.
    Dès que les .sky sont copiés dans le run, le futur Cooja est indépendant.
    """
    objective_function = str(config["objective_function"]).upper()

    validate_parameters(
        seed=seed,
        dio_interval_min=int(config["dio_interval_min"]),
        dio_interval_doublings=int(config["dio_interval_doublings"]),
        k=int(config["k"]),
        objective_function=objective_function,
        probing_enabled=bool(config["probing_enabled"]),
        probing_interval_s=config["probing_interval_s"],
        tx_power_dbm=int(config["tx_power_dbm"]),
    )
    validate_base_csc()

    run_dir = LOGS_DIR / run_name
    run_dir = prepare_run_directory(run_name, overwrite=run_dir.exists())
    status_file = run_dir / "status.json"

    metadata = build_metadata(
        run_name=run_name,
        seed=seed,
        dio_interval_min=int(config["dio_interval_min"]),
        dio_interval_doublings=int(config["dio_interval_doublings"]),
        k=int(config["k"]),
        objective_function=objective_function,
        probing_enabled=bool(config["probing_enabled"]),
        probing_interval_s=config["probing_interval_s"],
        tx_power_dbm=int(config["tx_power_dbm"]),
    )
    write_json(run_dir / "config.json", metadata)
    write_json(status_file, {"status": "preparing", "run_name": run_name, "parallel_mode": True})

    changed = write_project_conf(
        dio_interval_min=int(config["dio_interval_min"]),
        dio_interval_doublings=int(config["dio_interval_doublings"]),
        k=int(config["k"]),
        objective_function=objective_function,
        probing_enabled=bool(config["probing_enabled"]),
        probing_interval_s=config["probing_interval_s"],
        tx_power_dbm=int(config["tx_power_dbm"]),
    )
    shutil.copy2(PROJECT_CONF_FILE, run_dir / "project-conf.h")

    csc_file = run_dir / "simulation.csc"
    shutil.copy2(BASE_CSC_FILE, csc_file)

    write_json(
        status_file,
        {
            "status": "compiling",
            "run_name": run_name,
            "parallel_mode": True,
            "project_conf_changed": changed,
        },
    )

    # Une seed seulement : chaque run = configuration différente.
    # On force donc un build propre avant de figer les firmwares.
    compile_firmwares(run_dir=run_dir, clean_build=True)

    shared_server = RPL_UDP_DIR / "build" / "sky" / "udp-server.sky"
    shared_client = RPL_UDP_DIR / "build" / "sky" / "udp-client.sky"
    if not shared_server.exists() or not shared_client.exists():
        raise FileNotFoundError("Firmwares Sky absents après compilation.")

    fw_dir = run_dir / "firmware"
    fw_dir.mkdir(parents=True, exist_ok=True)
    private_server = fw_dir / "udp-server.sky"
    private_client = fw_dir / "udp-client.sky"
    shutil.copy2(shared_server, private_server)
    shutil.copy2(shared_client, private_client)

    patch_csc_firmware_paths(
        csc_file=csc_file,
        server_firmware=private_server,
        client_firmware=private_client,
    )

    write_json(
        status_file,
        {
            "status": "prepared",
            "run_name": run_name,
            "parallel_mode": True,
            "server_firmware": str(private_server),
            "client_firmware": str(private_client),
        },
    )
    return run_dir


def execute_prepared_run(*, run_dir: Path, run_name: str, seed: int) -> dict[str, Any]:
    """Worker : aucune compilation, uniquement Cooja headless."""
    gradlew = COOJA_DIR / "gradlew"
    if not gradlew.exists():
        raise FileNotFoundError(f"Gradle wrapper introuvable : {gradlew}")

    csc_file = run_dir / "simulation.csc"
    status_file = run_dir / "status.json"

    cooja_args = shlex.join(
        [
            "--no-gui",
            "--autostart",
            "--no-log-color",
            f"--random-seed={seed}",
            f"--logdir={run_dir}",
            f"--contiki={CONTIKI_DIR}",
            str(csc_file),
        ]
    )

    # Un Gradle indépendant par worker, avec un seul worker Gradle.
    command = [
        str(gradlew),
        "--no-daemon",
        "--max-workers=1",
        "run",
        f"--args={cooja_args}",
    ]

    (run_dir / "cooja_command.txt").write_text(shlex.join(command) + "\n", encoding="utf-8")
    write_json(status_file, {"status": "running", "run_name": run_name, "parallel_mode": True})

    started = time.time()
    console_log = run_dir / "cooja_console.log"
    with console_log.open("w", encoding="utf-8") as console:
        result = subprocess.run(
            command,
            cwd=COOJA_DIR,
            stdout=console,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    elapsed = time.time() - started

    if result.returncode != 0:
        raise RuntimeError(
            f"Cooja a échoué avec le code {result.returncode}. Voir {console_log}"
        )

    testlog = run_dir / "COOJA.testlog"
    if not testlog.exists():
        raise FileNotFoundError(f"COOJA.testlog absent pour {run_name}.")

    counts = inspect_testlog(testlog)
    if counts["client_summary"] == 0:
        raise RuntimeError(f"Aucun SUMMARY client pour {run_name}.")
    if counts["root_summary"] == 0:
        raise RuntimeError(f"Aucun ROOT_SUMMARY pour {run_name}.")
    if counts["tx"] == 0:
        raise RuntimeError(f"Aucun TX applicatif pour {run_name}.")
    # RX=0 est volontairement accepté comme résultat expérimental.

    result_summary = {
        "status": "success",
        "run_name": run_name,
        "wall_time_s": round(elapsed, 3),
        "counts": counts,
        "testlog": str(testlog),
        "parallel_mode": True,
    }
    write_json(run_dir / "result.json", result_summary)
    write_json(status_file, result_summary)

    return {
        "run_dir": run_dir,
        "run_name": run_name,
        "seed": seed,
        "wall_time_s": elapsed,
        "counts": counts,
    }


def cleanup_parallel_run(run_dir: Path) -> None:
    # Réutilise le nettoyage du générateur séquentiel.
    cleanup_successful_run(run_dir)
    fw_dir = run_dir / "firmware"
    if fw_dir.exists():
        shutil.rmtree(fw_dir, ignore_errors=True)


def build_jobs(
    configurations: list[dict[str, Any]],
    seeds: list[int],
    limit_runs: int | None,
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    run_number = 0

    for config_id, config in enumerate(configurations, start=1):
        for seed in seeds:
            run_number += 1
            run_name = make_run_name(
                run_number=run_number,
                config_id=config_id,
                seed=seed,
                objective_function=str(config["objective_function"]),
            )
            jobs.append(
                {
                    "run_number": run_number,
                    "config_id": config_id,
                    "seed": seed,
                    "run_name": run_name,
                    "config": config,
                }
            )

    return jobs if limit_runs is None else jobs[:limit_runs]


def process_completed_future(
    *,
    future: Future,
    job: dict[str, Any],
    dataset_run_names: set[str],
) -> bool:
    run_name = str(job["run_name"])
    config_id = int(job["config_id"])
    seed = int(job["seed"])
    config = job["config"]

    try:
        result = future.result()
        run_dir: Path = result["run_dir"]

        parsed = aggregate_run(run_dir=run_dir, config_id=config_id)
        # Ecriture CSV uniquement depuis le thread principal => pas de collision.
        write_run_csv(parsed, DATASET_FILE, append=True)
        dataset_run_names.add(run_name)

        write_status(
            run_name=run_name,
            config_id=config_id,
            seed=seed,
            config=config,
            status="SUCCESS",
        )

        delay = parsed.get("delay_avg_ms")
        delay_txt = f"{delay:.3f} ms" if delay is not None else "N/A"
        print(
            f"\n[SUCCESS] {run_name} | "
            f"PDR={parsed['pdr_global']:.2f}% | "
            f"delay={delay_txt} | "
            f"RX={parsed['unique_rx_count']}/{parsed['expected_app_tx']} | "
            f"wall={result['wall_time_s']/60:.1f} min"
        )

        cleanup_parallel_run(run_dir)
        return True

    except Exception as exc:
        write_status(
            run_name=run_name,
            config_id=config_id,
            seed=seed,
            config=config,
            status="FAILED",
            error=str(exc),
        )
        print(f"\n[FAILED] {run_name}: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False


def run_campaign(
    *,
    n_configs: int,
    seeds: list[int],
    workers: int,
    execute: bool,
    limit_runs: int | None,
    min_free_disk_gb: float,
    min_available_ram_gb: float,
) -> None:
    if workers < 1:
        raise ValueError("workers doit être >= 1")

    configurations = sample_configurations(n_configs)
    write_manifest(configurations)
    jobs = build_jobs(configurations, seeds, limit_runs)

    print("=" * 84)
    print("CAMPAGNE COOJA PARALLELE - SKY / RPL-LITE / 36 NOEUDS")
    print("=" * 84)
    print(f"Configurations sélectionnées : {len(configurations)}")
    print(f"Seeds                        : {seeds}")
    print(f"Runs campagne complète       : {len(configurations) * len(seeds)}")
    print(f"Workers Cooja                : {workers}")
    print(f"Runs de cette exécution      : {len(jobs)}")
    print(f"Dataset                      : {DATASET_FILE}")
    print(f"Manifest                     : {MANIFEST_FILE}")
    print_resources()
    print("=" * 84)

    if not execute:
        print("[DRY-RUN] Aucune simulation lancée.")
        print(
            f"Commande réelle : python3 {Path(__file__).name} "
            f"--execute --workers {workers}"
        )
        return

    dataset_run_names = load_dataset_run_names()
    pending = [j for j in jobs if j["run_name"] not in dataset_run_names]
    skipped = len(jobs) - len(pending)

    print(f"\nÀ exécuter : {len(pending)} | déjà dans dataset : {skipped}")
    if not pending:
        print("[OK] Tous les runs demandés existent déjà.")
        return

    success = 0
    failed = 0
    active: dict[Future, dict[str, Any]] = {}
    next_index = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        while next_index < len(pending) or active:

            # Remplit les slots. La préparation/compilation reste séquentielle.
            while next_index < len(pending) and len(active) < workers:
                ram_gb = get_available_ram_gb()
                disk_gb = get_free_disk_gb()

                if ram_gb < min_available_ram_gb:
                    if active:
                        print(
                            f"[RAM GUARD] {ram_gb:.2f} Go dispo < "
                            f"{min_available_ram_gb:.2f} Go : attente d'un worker."
                        )
                        break
                    raise RuntimeError(f"RAM insuffisante : {ram_gb:.2f} Go")

                if disk_gb < min_free_disk_gb:
                    if active:
                        print(
                            f"[DISK GUARD] {disk_gb:.2f} Go libres < "
                            f"{min_free_disk_gb:.2f} Go : attente des nettoyages."
                        )
                        break
                    raise RuntimeError(f"Disque insuffisant : {disk_gb:.2f} Go")

                job = pending[next_index]
                next_index += 1
                run_name = str(job["run_name"])
                config_id = int(job["config_id"])
                seed = int(job["seed"])
                config = job["config"]

                print("\n" + "-" * 84)
                print(
                    f"[PREPARE] {run_name} | cfg={config_id} | "
                    f"actifs={len(active)}/{workers}"
                )
                print(
                    f"Imin={config['dio_interval_min']} | "
                    f"doublings={config['dio_interval_doublings']} | "
                    f"k={config['k']} | OF={config['objective_function']} | "
                    f"probing={config['probing_enabled']} | "
                    f"probe_s={config['probing_interval_s']} | "
                    f"TX={config['tx_power_dbm']} dBm"
                )
                print_resources()

                try:
                    run_dir = prepare_frozen_run(
                        run_name=run_name,
                        seed=seed,
                        config=config,
                    )
                    future = executor.submit(
                        execute_prepared_run,
                        run_dir=run_dir,
                        run_name=run_name,
                        seed=seed,
                    )
                    active[future] = job
                    print(
                        f"[START] {run_name} | workers actifs={len(active)}/{workers}"
                    )
                except Exception as exc:
                    failed += 1
                    write_status(
                        run_name=run_name,
                        config_id=config_id,
                        seed=seed,
                        config=config,
                        status="FAILED",
                        error=str(exc),
                    )
                    print(f"[FAILED-PREPARE] {run_name}: {type(exc).__name__}: {exc}")
                    traceback.print_exc()

            if active:
                done, _ = wait(active.keys(), return_when=FIRST_COMPLETED)
                for future in done:
                    job = active.pop(future)
                    if process_completed_future(
                        future=future,
                        job=job,
                        dataset_run_names=dataset_run_names,
                    ):
                        success += 1
                    else:
                        failed += 1
                print_resources()
            elif next_index < len(pending):
                raise RuntimeError(
                    "Il reste des jobs mais aucun worker actif. Vérifie RAM/disque."
                )

    print("\n" + "=" * 84)
    print("EXECUTION TERMINEE")
    print("=" * 84)
    print(f"Runs demandés      : {len(jobs)}")
    print(f"Déjà présents/skip : {skipped}")
    print(f"SUCCESS nouveaux   : {success}")
    print(f"FAILED             : {failed}")
    print(f"Dataset            : {DATASET_FILE}")
    print_resources()


def parse_seed_list(value: str) -> list[int]:
    try:
        seeds = [int(x.strip()) for x in value.split(",") if x.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Seeds invalides") from exc
    if not seeds:
        raise argparse.ArgumentTypeError("Liste de seeds vide")
    if len(set(seeds)) != len(seeds):
        raise argparse.ArgumentTypeError("Seeds dupliquées")
    return seeds


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Campagne Cooja parallèle : compilation séquentielle, "
            "firmwares figés par run, 5 Cooja simultanés par défaut."
        )
    )
    p.add_argument("--n-configs", type=int, default=DEFAULT_N_CONFIGS)
    p.add_argument("--seeds", type=parse_seed_list, default=DEFAULT_SEEDS)
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--execute", action="store_true")
    p.add_argument(
        "--limit-runs",
        type=int,
        default=None,
        help=(
            "N'exécute que les N premiers runs. Les runs réussis sont gardés "
            "dans le vrai dataset et seront skippés lors de la reprise."
        ),
    )
    p.add_argument("--min-free-disk-gb", type=float, default=DEFAULT_MIN_FREE_DISK_GB)
    p.add_argument(
        "--min-available-ram-gb",
        type=float,
        default=DEFAULT_MIN_AVAILABLE_RAM_GB,
    )
    return p.parse_args()


def main() -> int:
    a = parse_args()
    if a.limit_runs is not None and a.limit_runs <= 0:
        raise SystemExit("--limit-runs doit être > 0")

    run_campaign(
        n_configs=a.n_configs,
        seeds=a.seeds,
        workers=a.workers,
        execute=a.execute,
        limit_runs=a.limit_runs,
        min_free_disk_gb=a.min_free_disk_gb,
        min_available_ram_gb=a.min_available_ram_gb,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
