from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


# ============================================================
# CHEMINS DU PROJET
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Quand ce fichier est copié dans ~/Bureau/projetStage/cooja_automation,
# PROJECT_ROOT devient ~/Bureau/projetStage.
CONTIKI_DIR = PROJECT_ROOT / "contiki-ng"
COOJA_DIR = CONTIKI_DIR / "tools" / "cooja"
RPL_UDP_DIR = CONTIKI_DIR / "examples" / "rpl-udp"

BASE_CSC_FILE = RPL_UDP_DIR / "simulation_rpl.csc"
PROJECT_CONF_FILE = RPL_UDP_DIR / "project-conf.h"

LOGS_DIR = PROJECT_ROOT / "cooja_automation" / "logs"


# ============================================================
# SCENARIO FIXE DE LA NOUVELLE CAMPAGNE
# ============================================================

NB_NODES = 36
NB_CLIENTS = 35
GRID_SIZE = 6
GRID_SPACING_M = 30.0
ROOT_ID = 1
ROOT_POSITION = (60.0, 60.0)

TRAFFIC_WINDOW_SECONDS = 600
TRAFFIC_START_SECONDS = 600
PAYLOAD_SIZE_BYTES = 10

# 6 h / 600 s = 36 fenêtres expérimentales
MEASUREMENT_WINDOWS = 36

MEASUREMENT_DURATION_SECONDS = (
    MEASUREMENT_WINDOWS * TRAFFIC_WINDOW_SECONDS
)

# Durée scientifique :
# 600 s de convergence + 21600 s de mesure = 22200 s
SIMULATION_DURATION_SECONDS = (
    TRAFFIC_START_SECONDS + MEASUREMENT_DURATION_SECONDS
)

# Petite marge Cooja afin que la fenêtre 35 se termine
# malgré le délai de démarrage des motes.
SIMULATION_GRACE_SECONDS = 100

SIMULATION_TIMEOUT_MS = (
    SIMULATION_DURATION_SECONDS
    + SIMULATION_GRACE_SECONDS
) * 1000

EXPECTED_CLIENT_SUMMARIES = NB_CLIENTS * MEASUREMENT_WINDOWS
EXPECTED_ROOT_SUMMARIES = MEASUREMENT_WINDOWS
EXPECTED_TX = NB_CLIENTS * MEASUREMENT_WINDOWS

# Le lifetime n'est PAS une variable ML.
# 0xFF est la valeur RPL "infinite lifetime" dans RPL-Lite.
RPL_DEFAULT_LIFETIME = 0xFF
RPL_DEFAULT_LIFETIME_UNIT_SECONDS = 60

# Le driver CC2420 de Contiki-NG utilise ces 8 niveaux matériels.
CC2420_TX_POWER_LEVELS_DBM = (
    -25,
    -15,
    -10,
    -7,
    -5,
    -3,
    -1,
    0,
)

# Limite pratique liée à l'implémentation RPL-Lite :
# new_dio_interval() calcule 1UL << dio_intcurrent puis convertit en ticks.
# Sur Sky, on garde donc un exposant maximal raisonnable.
MAX_DIO_EXPONENT = 24


# ============================================================
# OUTILS GENERAUX
# ============================================================


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )



def write_text_if_changed(path: Path, content: str) -> bool:
    """Ecrit le fichier uniquement si son contenu change."""

    if path.exists():
        old_content = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        if old_content == content:
            return False

    path.write_text(
        content,
        encoding="utf-8",
    )

    return True



def sanitize_run_name(run_name: str) -> str:
    run_name = run_name.strip()

    if not run_name:
        raise ValueError("run_name ne peut pas être vide.")

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_name):
        raise ValueError(
            "run_name ne peut contenir que lettres, chiffres, "
            "underscore, tiret et point."
        )

    if run_name in {".", ".."}:
        raise ValueError("run_name invalide.")

    return run_name


# ============================================================
# VALIDATION DU SCENARIO DE BASE
# ============================================================


def _mote_id(mote: ET.Element) -> int | None:
    for interface in mote.findall("interface_config"):
        id_element = interface.find("id")

        if id_element is not None and id_element.text:
            try:
                return int(id_element.text.strip())
            except ValueError:
                return None

    return None



def _mote_position(mote: ET.Element) -> tuple[float, float] | None:
    for interface in mote.findall("interface_config"):
        x_element = interface.find("x")
        y_element = interface.find("y")

        if (
            x_element is not None
            and y_element is not None
            and x_element.text
            and y_element.text
        ):
            try:
                return (
                    float(x_element.text.strip()),
                    float(y_element.text.strip()),
                )
            except ValueError:
                return None

    return None



def validate_base_csc() -> None:
    """
    Verifie que simulation_rpl.csc est bien le scenario fixe 36 Sky.

    Cette fonction ne modifie jamais le fichier.
    """

    if not BASE_CSC_FILE.exists():
        raise FileNotFoundError(
            f"Scenario Cooja introuvable : {BASE_CSC_FILE}"
        )

    try:
        tree = ET.parse(BASE_CSC_FILE)
    except ET.ParseError as exc:
        raise RuntimeError(
            f"XML invalide dans {BASE_CSC_FILE}: {exc}"
        ) from exc

    root = tree.getroot()
    simulation = root.find("simulation")

    if simulation is None:
        raise RuntimeError(
            "Balise <simulation> introuvable dans simulation_rpl.csc."
        )

    # --------------------------------------------------------
    # Radio medium fixe
    # --------------------------------------------------------

    radio = simulation.find("radiomedium")

    if radio is None:
        raise RuntimeError("Balise <radiomedium> introuvable.")

    radio_text = "".join(radio.itertext())

    if "UDGM" not in radio_text:
        raise RuntimeError(
            "Le scenario de base doit utiliser UDGM."
        )

    expected_radio = {
        "transmitting_range": 50.0,
        "interference_range": 100.0,
        "success_ratio_tx": 1.0,
        "success_ratio_rx": 1.0,
    }

    for tag, expected in expected_radio.items():
        element = radio.find(tag)

        if element is None or element.text is None:
            raise RuntimeError(f"<{tag}> introuvable dans le .csc.")

        value = float(element.text.strip())

        if abs(value - expected) > 1e-9:
            raise RuntimeError(
                f"{tag} doit rester fixe à {expected}, valeur trouvée={value}."
            )

    # --------------------------------------------------------
    # 36 motes, IDs 1..36
    # --------------------------------------------------------

    motes = simulation.findall("mote")

    if len(motes) != NB_NODES:
        raise RuntimeError(
            f"Le scenario doit contenir exactement {NB_NODES} motes, "
            f"{len(motes)} trouvés."
        )

    ids = []
    positions: dict[int, tuple[float, float]] = {}
    types: dict[int, str] = {}

    for mote in motes:
        mote_id = _mote_id(mote)

        if mote_id is None:
            raise RuntimeError("Un mote ne possède pas d'ID exploitable.")

        ids.append(mote_id)

        position = _mote_position(mote)

        if position is None:
            raise RuntimeError(
                f"Position introuvable pour le mote ID {mote_id}."
            )

        positions[mote_id] = position

        type_element = mote.find("motetype_identifier")

        if type_element is None or not type_element.text:
            raise RuntimeError(
                f"motetype_identifier absent pour ID {mote_id}."
            )

        types[mote_id] = type_element.text.strip()

    expected_ids = list(range(1, NB_NODES + 1))

    if sorted(ids) != expected_ids:
        raise RuntimeError(
            f"IDs attendus 1..36, IDs trouvés : {sorted(ids)}"
        )

    # --------------------------------------------------------
    # Grille 6x6 / root au centre
    # --------------------------------------------------------

    expected_positions = {
        (
            col * GRID_SPACING_M,
            row * GRID_SPACING_M,
        )
        for row in range(GRID_SIZE)
        for col in range(GRID_SIZE)
    }

    found_positions = set(positions.values())

    if found_positions != expected_positions:
        raise RuntimeError(
            "Les positions du .csc ne correspondent plus à la grille "
            "6x6 fixe avec espacement de 30 m."
        )

    if positions.get(ROOT_ID) != ROOT_POSITION:
        raise RuntimeError(
            f"Le root ID 1 doit être en {ROOT_POSITION}, "
            f"trouvé={positions.get(ROOT_ID)}."
        )

    # --------------------------------------------------------
    # Root/client types
    # --------------------------------------------------------

    if types[ROOT_ID] == types[2]:
        raise RuntimeError(
            "Le root ID 1 et les clients utilisent le même mote type."
        )

    client_types = {types[mote_id] for mote_id in range(2, 37)}

    if len(client_types) != 1:
        raise RuntimeError(
            "Les 35 clients doivent utiliser un seul mote type."
        )

    # --------------------------------------------------------
    # Durée ScriptRunner fixe
    # --------------------------------------------------------

    csc_text = BASE_CSC_FILE.read_text(
        encoding="utf-8",
        errors="replace",
    )

    timeout_pattern = rf"TIMEOUT\(\s*{SIMULATION_TIMEOUT_MS}\s*,"

    if re.search(timeout_pattern, csc_text) is None:
        raise RuntimeError(
            "Le ScriptRunner du .csc doit contenir "
            f"TIMEOUT({SIMULATION_TIMEOUT_MS}, ...)."
        )


# ============================================================
# VALIDATION DES PARAMETRES VARIABLES
# ============================================================


def validate_parameters(
    *,
    seed: int,
    dio_interval_min: int,
    dio_interval_doublings: int,
    k: int,
    objective_function: str,
    probing_enabled: bool,
    probing_interval_s: int | None,
    tx_power_dbm: int,
) -> None:

    if seed < 0:
        raise ValueError("seed doit être >= 0.")

    if not (0 <= dio_interval_min <= 24):
        raise ValueError(
            "dio_interval_min doit être compris entre 0 et 24."
        )

    if not (0 <= dio_interval_doublings <= 24):
        raise ValueError(
            "dio_interval_doublings doit être compris entre 0 et 24."
        )

    max_exponent = dio_interval_min + dio_interval_doublings

    if max_exponent > MAX_DIO_EXPONENT:
        raise ValueError(
            "dio_interval_min + dio_interval_doublings "
            f"doit être <= {MAX_DIO_EXPONENT} pour Sky/RPL-Lite. "
            f"Valeur actuelle : {max_exponent}."
        )

    if not (0 <= k <= 255):
        raise ValueError("k doit être compris entre 0 et 255.")

    objective_function = objective_function.strip().upper()

    if objective_function not in {"OF0", "MRHOF"}:
        raise ValueError(
            "objective_function doit valoir OF0 ou MRHOF."
        )

    if probing_enabled:
        if probing_interval_s is None or probing_interval_s <= 0:
            raise ValueError(
                "Quand probing_enabled=True, probing_interval_s "
                "doit être > 0."
            )

    if tx_power_dbm not in CC2420_TX_POWER_LEVELS_DBM:
        raise ValueError(
            f"tx_power_dbm={tx_power_dbm} non supporté. "
            "Niveaux CC2420 autorisés : "
            + ", ".join(str(v) for v in CC2420_TX_POWER_LEVELS_DBM)
        )


# ============================================================
# GENERATION DE project-conf.h
# ============================================================


def write_project_conf(
    *,
    dio_interval_min: int,
    dio_interval_doublings: int,
    k: int,
    objective_function: str,
    probing_enabled: bool,
    probing_interval_s: int | None,
    tx_power_dbm: int,
) -> bool:
    """
    Genere project-conf.h pour UNE configuration expérimentale.

    Ne sont variables que :
      - DIOIntervalMin
      - DIOIntervalDoublings
      - k
      - OF0/MRHOF
      - probing OFF/ON + intervalle
      - TX power en dBm

    Le reste du scenario reste fixe.
    """

    objective_function = objective_function.strip().upper()

    if objective_function == "MRHOF":
        rpl_ocp = "RPL_OCP_MRHOF"
    else:
        rpl_ocp = "RPL_OCP_OF0"

    probing_value = 1 if probing_enabled else 0

    probing_block = ""

    if probing_enabled:
        assert probing_interval_s is not None

        probing_block = (
            "#define RPL_CONF_PROBING_INTERVAL "
            f"({probing_interval_s} * CLOCK_SECOND)\n"
        )

    content = f"""\
#ifndef PROJECT_CONF_H_
#define PROJECT_CONF_H_

/* =========================================================
 * ENERGEST
 * ========================================================= */
#define ENERGEST_CONF_ON 1

/* =========================================================
 * RPL / TRICKLE - VARIABLES EXPERIMENTALES
 * ========================================================= */
#define RPL_CONF_DIO_INTERVAL_MIN {dio_interval_min}
#define RPL_CONF_DIO_INTERVAL_DOUBLINGS {dio_interval_doublings}
#define RPL_CONF_DIO_REDUNDANCY {k}

/* =========================================================
 * OBJECTIVE FUNCTION - VARIABLE EXPERIMENTALE
 * ========================================================= */
#define RPL_CONF_SUPPORTED_OFS {{&rpl_of0, &rpl_mrhof}}
#define RPL_CONF_OF_OCP {rpl_ocp}

/* =========================================================
 * PROBING - VARIABLE EXPERIMENTALE
 * ========================================================= */
#define RPL_CONF_WITH_PROBING {probing_value}
{probing_block}\
/* =========================================================
 * ROUTE LIFETIME - FIXE
 * 0xFF = infinite lifetime dans RPL-Lite
 * ========================================================= */
#define RPL_CONF_DEFAULT_LIFETIME 0xFF
#define RPL_CONF_DEFAULT_LIFETIME_UNIT {RPL_DEFAULT_LIFETIME_UNIT_SECONDS}

/* =========================================================
 * TRAFIC APPLICATIF - FIXE
 * 1 paquet/client/fenetre de 600 s, payload 10 octets
 * ========================================================= */
#define APP_CONF_TRAFFIC_WINDOW_SECONDS {TRAFFIC_WINDOW_SECONDS}
#define APP_CONF_TRAFFIC_START_SECONDS {TRAFFIC_START_SECONDS}
#define APP_CONF_MEASUREMENT_WINDOWS {MEASUREMENT_WINDOWS}
#define APP_CONF_PAYLOAD_SIZE {PAYLOAD_SIZE_BYTES}

/* =========================================================
 * CC2420 TX POWER - VARIABLE EXPERIMENTALE, en dBm
 * ========================================================= */
#define APP_CONF_TX_POWER_DBM {tx_power_dbm}

#endif /* PROJECT_CONF_H_ */
"""

    return write_text_if_changed(
        PROJECT_CONF_FILE,
        content,
    )


# ============================================================
# PREPARATION DU DOSSIER DE RUN
# ============================================================


def prepare_run_directory(
    run_name: str,
    *,
    overwrite: bool,
) -> Path:

    LOGS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    run_dir = LOGS_DIR / run_name

    if run_dir.exists():
        if not overwrite:
            raise FileExistsError(
                f"Le run existe déjà : {run_dir}. "
                "Utilise overwrite=True ou --overwrite pour le remplacer."
            )

        shutil.rmtree(run_dir)

    run_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    return run_dir


# ============================================================
# COMPILATION SKY
# ============================================================


def _run_and_log(
    command: list[str],
    *,
    cwd: Path,
    log_file: Path,
) -> subprocess.CompletedProcess[str]:

    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    log_file.write_text(
        result.stdout or "",
        encoding="utf-8",
        errors="replace",
    )

    return result



def compile_firmwares(
    *,
    run_dir: Path,
    clean_build: bool,
) -> None:

    compile_log = run_dir / "compile.log"
    accumulated = []

    if clean_build:
        clean = subprocess.run(
            ["make", "TARGET=sky", "clean"],
            cwd=RPL_UDP_DIR,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        accumulated.append(
            "$ make TARGET=sky clean\n"
            + (clean.stdout or "")
            + "\n"
        )

        if clean.returncode != 0:
            compile_log.write_text(
                "".join(accumulated),
                encoding="utf-8",
            )

            raise RuntimeError(
                f"make clean a échoué. Voir {compile_log}"
            )

    jobs = max(1, min(os.cpu_count() or 1, 12))

    command = [
        "make",
        f"-j{jobs}",
        "TARGET=sky",
        "udp-server",
        "udp-client",
    ]

    build = subprocess.run(
        command,
        cwd=RPL_UDP_DIR,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    accumulated.append(
        "$ " + shlex.join(command) + "\n"
        + (build.stdout or "")
        + "\n"
    )

    compile_log.write_text(
        "".join(accumulated),
        encoding="utf-8",
        errors="replace",
    )

    if build.returncode != 0:
        raise RuntimeError(
            f"Compilation Sky échouée. Voir {compile_log}"
        )

    server_firmware = RPL_UDP_DIR / "build" / "sky" / "udp-server.sky"
    client_firmware = RPL_UDP_DIR / "build" / "sky" / "udp-client.sky"

    for firmware in (server_firmware, client_firmware):
        if not firmware.exists():
            raise FileNotFoundError(
                f"Firmware attendu absent après compilation : {firmware}"
            )


# ============================================================
# META-DONNEES DU RUN
# ============================================================


def build_metadata(
    *,
    run_name: str,
    seed: int,
    dio_interval_min: int,
    dio_interval_doublings: int,
    k: int,
    objective_function: str,
    probing_enabled: bool,
    probing_interval_s: int | None,
    tx_power_dbm: int,
) -> dict[str, Any]:

    effective_probing_interval = (
        probing_interval_s
        if probing_enabled
        else None
    )

    imin_ms = 2 ** dio_interval_min
    imax_exponent = dio_interval_min + dio_interval_doublings
    imax_ms = 2 ** imax_exponent

    return {
        "run_name": run_name,
        "seed": seed,
        "parameters": {
            "dio_interval_min": dio_interval_min,
            "dio_interval_min_ms": imin_ms,
            "dio_interval_doublings": dio_interval_doublings,
            "dio_interval_max_exponent": imax_exponent,
            "dio_interval_max_ms": imax_ms,
            "k": k,
            "objective_function": objective_function.strip().upper(),
            "probing_enabled": bool(probing_enabled),
            "probing_interval_s": effective_probing_interval,
            "tx_power_dbm": tx_power_dbm,
        },
        "fixed_scenario": {
            "platform": "Sky / Tmote Sky",
            "radio": "CC2420",
            "routing": "RPL-Lite",
            "mac": "CSMA",
            "radio_medium": "UDGM",
            "nb_nodes": NB_NODES,
            "nb_clients": NB_CLIENTS,
            "root_id": ROOT_ID,
            "grid": "6x6",
            "grid_spacing_m": GRID_SPACING_M,
            "root_position": list(ROOT_POSITION),
            "udgm_transmitting_range_m": 50.0,
            "udgm_interference_range_m": 100.0,
            "udgm_success_ratio_tx": 1.0,
            "udgm_success_ratio_rx": 1.0,
            "traffic_window_s": TRAFFIC_WINDOW_SECONDS,
            "traffic_start_s": TRAFFIC_START_SECONDS,
            "messages_per_client_per_window": 1,
            "messages_per_network_per_window": NB_CLIENTS,
            "payload_bytes": PAYLOAD_SIZE_BYTES,
            "measurement_windows": MEASUREMENT_WINDOWS,
            "measurement_duration_s": MEASUREMENT_DURATION_SECONDS,
            "simulation_duration_s": SIMULATION_DURATION_SECONDS,
            "simulation_grace_s": SIMULATION_GRACE_SECONDS,
            "simulation_timeout_s": (
                SIMULATION_DURATION_SECONDS
                + SIMULATION_GRACE_SECONDS
            ),
            "rpl_default_lifetime": "0xFF/infinite",
            "rpl_default_lifetime_unit_s": RPL_DEFAULT_LIFETIME_UNIT_SECONDS,
        },
        "files": {
            "base_csc": str(BASE_CSC_FILE),
            "project_conf": str(PROJECT_CONF_FILE),
        },
    }


# ============================================================
# ANALYSE MINIMALE DU TESTLOG
# ============================================================


def inspect_testlog(testlog: Path) -> dict[str, int]:

    counts = {
        "client_summary": 0,
        "root_summary": 0,
        "tx": 0,
        "rx": 0,
        "traffic_start_client": 0,
        "traffic_start_root": 0,
    }

    with testlog.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for line in handle:
            if "ROOT_SUMMARY," in line:
                counts["root_summary"] += 1

            elif "SUMMARY," in line:
                counts["client_summary"] += 1

            if "TX,node=" in line:
                counts["tx"] += 1

            if "RX,node=" in line:
                counts["rx"] += 1

            if "TRAFFIC_START_ROOT" in line:
                counts["traffic_start_root"] += 1

            elif "TRAFFIC_START," in line:
                counts["traffic_start_client"] += 1

    return counts


# ============================================================
# LANCEMENT D'UN RUN COOJA
# ============================================================


def run_simulation(
    *,
    seed: int,
    dio_interval_min: int,
    dio_interval_doublings: int,
    k: int,
    objective_function: str,
    probing_enabled: bool,
    probing_interval_s: int | None,
    tx_power_dbm: int,
    run_name: str,
    clean_build: bool = True,
    overwrite: bool = False,
) -> Path:
    """
    Lance UNE simulation Cooja de la nouvelle campagne.

    Le .csc de base reste fixe :
      - 36 Sky
      - grille 6x6
      - root ID 1
      - 35 clients
      - UDGM fixe
      - durée fixe

    Les seules variables expérimentales sont celles passées ici.
    """

    run_name = sanitize_run_name(run_name)
    objective_function = objective_function.strip().upper()

    validate_parameters(
        seed=seed,
        dio_interval_min=dio_interval_min,
        dio_interval_doublings=dio_interval_doublings,
        k=k,
        objective_function=objective_function,
        probing_enabled=probing_enabled,
        probing_interval_s=probing_interval_s,
        tx_power_dbm=tx_power_dbm,
    )

    validate_base_csc()

    if not COOJA_DIR.exists():
        raise FileNotFoundError(
            f"Dossier Cooja introuvable : {COOJA_DIR}"
        )

    gradlew = COOJA_DIR / "gradlew"

    if not gradlew.exists():
        raise FileNotFoundError(
            f"Gradle wrapper introuvable : {gradlew}"
        )

    run_dir = prepare_run_directory(
        run_name,
        overwrite=overwrite,
    )

    status_file = run_dir / "status.json"

    metadata = build_metadata(
        run_name=run_name,
        seed=seed,
        dio_interval_min=dio_interval_min,
        dio_interval_doublings=dio_interval_doublings,
        k=k,
        objective_function=objective_function,
        probing_enabled=probing_enabled,
        probing_interval_s=probing_interval_s,
        tx_power_dbm=tx_power_dbm,
    )

    write_json(
        run_dir / "config.json",
        metadata,
    )

    write_json(
        status_file,
        {
            "status": "preparing",
            "run_name": run_name,
        },
    )

    try:
        # ----------------------------------------------------
        # 1. Générer project-conf.h
        # ----------------------------------------------------

        changed = write_project_conf(
            dio_interval_min=dio_interval_min,
            dio_interval_doublings=dio_interval_doublings,
            k=k,
            objective_function=objective_function,
            probing_enabled=probing_enabled,
            probing_interval_s=probing_interval_s,
            tx_power_dbm=tx_power_dbm,
        )

        # Copie exacte utilisée pour ce run : traçabilité.
        shutil.copy2(
            PROJECT_CONF_FILE,
            run_dir / "project-conf.h",
        )

        # ----------------------------------------------------
        # 2. Copier le .csc FIXE, sans toucher à la topologie
        # ----------------------------------------------------

        experiment_csc = run_dir / "simulation.csc"

        shutil.copy2(
            BASE_CSC_FILE,
            experiment_csc,
        )

        # ----------------------------------------------------
        # 3. Compiler Sky
        # ----------------------------------------------------

        write_json(
            status_file,
            {
                "status": "compiling",
                "run_name": run_name,
                "project_conf_changed": changed,
            },
        )

        compile_firmwares(
            run_dir=run_dir,
            clean_build=clean_build,
        )

        # ----------------------------------------------------
        # 4. Affichage du run
        # ----------------------------------------------------

        imin_ms = 2 ** dio_interval_min
        max_exp = dio_interval_min + dio_interval_doublings
        imax_ms = 2 ** max_exp

        print("\n" + "=" * 78)
        print(f"RUN                    : {run_name}")
        print(f"Seed                   : {seed}")
        print(f"DIOIntervalMin         : {dio_interval_min} -> {imin_ms} ms")
        print(f"DIOIntervalDoublings   : {dio_interval_doublings}")
        print(f"Imax effectif          : 2^{max_exp} ms = {imax_ms} ms")
        print(f"k                      : {k}")
        print(f"Objective Function     : {objective_function}")
        print(f"Probing                : {'ON' if probing_enabled else 'OFF'}")

        if probing_enabled:
            print(f"Probing interval       : {probing_interval_s} s")
        else:
            print("Probing interval       : N/A")

        print(f"TX power demandé       : {tx_power_dbm} dBm")
        print(f"Nodes                  : {NB_NODES} (1 root + {NB_CLIENTS} clients)")
        print(f"Traffic                : 1 paquet/client/{TRAFFIC_WINDOW_SECONDS}s")
        print(f"Payload                : {PAYLOAD_SIZE_BYTES} octets")
        print(f"Mesure                 : {MEASUREMENT_DURATION_SECONDS // 3600} h")
        print("=" * 78)

        # ----------------------------------------------------
        # 5. Lancer Cooja headless
        # ----------------------------------------------------

        cooja_args = shlex.join(
            [
                "--no-gui",
                "--autostart",
                "--no-log-color",
                f"--random-seed={seed}",
                f"--logdir={run_dir}",
                f"--contiki={CONTIKI_DIR}",
                str(experiment_csc),
            ]
        )

        command = [
            str(gradlew),
            "run",
            f"--args={cooja_args}",
        ]

        (run_dir / "cooja_command.txt").write_text(
            shlex.join(command) + "\n",
            encoding="utf-8",
        )

        write_json(
            status_file,
            {
                "status": "running",
                "run_name": run_name,
            },
        )

        started_at = time.time()

        cooja_console_log = run_dir / "cooja_console.log"

        with cooja_console_log.open(
            "w",
            encoding="utf-8",
        ) as console:
            result = subprocess.run(
                command,
                cwd=COOJA_DIR,
                stdout=console,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )

        elapsed_wall_s = time.time() - started_at

        if result.returncode != 0:
            raise RuntimeError(
                f"Cooja a échoué avec le code {result.returncode}. "
                f"Voir {cooja_console_log}"
            )

        # ----------------------------------------------------
        # 6. Vérifier le log produit
        # ----------------------------------------------------

        testlog = run_dir / "COOJA.testlog"

        if not testlog.exists():
            raise FileNotFoundError(
                f"COOJA.testlog absent pour {run_name}."
            )

        counts = inspect_testlog(testlog)

        if counts["client_summary"] != EXPECTED_CLIENT_SUMMARIES:
            raise RuntimeError(
                f"Nombre de SUMMARY clients incorrect : "
                f"{counts['client_summary']} au lieu de "
                f"{EXPECTED_CLIENT_SUMMARIES}."
            )

        if counts["root_summary"] != EXPECTED_ROOT_SUMMARIES:
            raise RuntimeError(
                f"Nombre de ROOT_SUMMARY incorrect : "
                f"{counts['root_summary']} au lieu de "
                f"{EXPECTED_ROOT_SUMMARIES}."
            )

        if counts["tx"] != EXPECTED_TX:
            raise RuntimeError(
                f"Nombre de TX applicatifs incorrect : "
                f"{counts['tx']} au lieu de {EXPECTED_TX}."
            )

        # Un RX=0 peut être un résultat expérimental réel si une
        # configuration radio/RPL déconnecte complètement le réseau.
        # On ne bloque donc pas le run pour cette raison.

        result_summary = {
            "status": "success",
            "run_name": run_name,
            "wall_time_s": round(elapsed_wall_s, 3),
            "counts": counts,
            "testlog": str(testlog),
        }

        write_json(
            run_dir / "result.json",
            result_summary,
        )

        write_json(
            status_file,
            result_summary,
        )

        print(
            f"[OK] {run_name} terminé | "
            f"SUMMARY clients={counts['client_summary']} | "
            f"ROOT_SUMMARY={counts['root_summary']} | "
            f"TX={counts['tx']} | RX={counts['rx']}"
        )

        if counts["rx"] == 0:
            print(
                "[WARNING] Aucun paquet reçu par le root. "
                "Le run est conservé car cela peut représenter "
                "une configuration réseau non connectée."
            )

        return testlog

    except Exception as exc:
        write_json(
            status_file,
            {
                "status": "failed",
                "run_name": run_name,
                "error": str(exc),
            },
        )

        raise


# ============================================================
# CLI : LANCEMENT MANUEL D'UN RUN
# ============================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Lance une simulation Cooja Sky/RPL-Lite de la campagne 36 noeuds."
        )
    )

    parser.add_argument(
        "--run-name",
        required=True,
        help="Nom unique du run, ex: pilot_rfc_of0_tx0",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=1,
    )

    parser.add_argument(
        "--dio-interval-min",
        type=int,
        default=3,
        help="DIOIntervalMin n, Imin=2^n ms. Défaut CLI: 3.",
    )

    parser.add_argument(
        "--dio-interval-doublings",
        type=int,
        default=20,
        help="Nombre de doublements Trickle. Défaut CLI: 20.",
    )

    parser.add_argument(
        "--k",
        type=int,
        default=10,
        help="Constante de redondance Trickle. Défaut CLI: 10.",
    )

    parser.add_argument(
        "--objective-function",
        choices=("OF0", "MRHOF"),
        default="OF0",
    )

    parser.add_argument(
        "--probing",
        type=int,
        choices=(0, 1),
        default=1,
        help="0=OFF, 1=ON.",
    )

    parser.add_argument(
        "--probing-interval-s",
        type=int,
        default=90,
        help="Intervalle de probing si probing=1.",
    )

    parser.add_argument(
        "--tx-power-dbm",
        type=int,
        choices=CC2420_TX_POWER_LEVELS_DBM,
        default=0,
        help="Puissance CC2420 demandée en dBm.",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Remplace un dossier de run portant déjà ce nom.",
    )

    parser.add_argument(
        "--no-clean-build",
        action="store_true",
        help="Ne lance pas make clean avant compilation.",
    )

    return parser.parse_args()



def main() -> int:
    args = parse_args()

    probing_enabled = bool(args.probing)

    probing_interval_s = (
        args.probing_interval_s
        if probing_enabled
        else None
    )

    try:
        testlog = run_simulation(
            seed=args.seed,
            dio_interval_min=args.dio_interval_min,
            dio_interval_doublings=args.dio_interval_doublings,
            k=args.k,
            objective_function=args.objective_function,
            probing_enabled=probing_enabled,
            probing_interval_s=probing_interval_s,
            tx_power_dbm=args.tx_power_dbm,
            run_name=args.run_name,
            clean_build=not args.no_clean_build,
            overwrite=args.overwrite,
        )

    except Exception as exc:
        print(
            f"\n[ERROR] {exc}",
            file=sys.stderr,
        )
        return 1

    print(f"\nLog final : {testlog}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
