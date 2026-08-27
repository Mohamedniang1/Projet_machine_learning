#!/usr/bin/env python3

from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


# ============================================================
# CHEMINS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONTIKI_DIR = (
    PROJECT_ROOT
    / "contiki-ng"
)

COOJA_DIR = (
    CONTIKI_DIR
    / "tools"
    / "cooja"
)

RPL_UDP_DIR = (
    CONTIKI_DIR
    / "examples"
    / "rpl-udp"
)

BASE_CSC_FILE = (
    RPL_UDP_DIR
    / "simulation_rpl.csc"
)

PROJECT_CONF_FILE = (
    RPL_UDP_DIR
    / "project-conf.h"
)

LOGS_DIR = (
    PROJECT_ROOT
    / "cooja_automation"
    / "logs"
)


# ============================================================
# OBJECTIVE FUNCTIONS
# ============================================================

SUPPORTED_OBJECTIVE_FUNCTIONS = {
    "MRHOF": "RPL_OCP_MRHOF",
    "OF0": "RPL_OCP_OF0",
}


# ============================================================
# OUTILS CSC
# ============================================================

def count_motes_in_csc(
    csc_file: Path,
) -> int:
    """
    Compte automatiquement le nombre de balises <mote>
    présentes dans <simulation>.
    """

    if not csc_file.exists():
        raise FileNotFoundError(
            f"Fichier .csc introuvable : {csc_file}"
        )

    try:
        tree = ET.parse(csc_file)

    except ET.ParseError as exc:
        raise RuntimeError(
            f"XML invalide dans {csc_file} : {exc}"
        ) from exc

    root = tree.getroot()

    simulation = root.find("simulation")

    if simulation is None:
        raise RuntimeError(
            "Balise <simulation> introuvable."
        )

    return len(
        simulation.findall("mote")
    )


def get_mote_id(
    mote: ET.Element,
) -> int | None:
    """
    Retourne l'ID Contiki d'un mote.
    """

    for interface in mote.findall(
        "interface_config"
    ):

        id_element = interface.find("id")

        if id_element is not None:
            try:
                return int(id_element.text)

            except (
                TypeError,
                ValueError,
            ):
                return None

    return None


def get_mote_ids_from_csc(
    csc_file: Path,
) -> list[int]:
    """
    Retourne tous les IDs des motes présents
    dans le fichier .csc.
    """

    tree = ET.parse(csc_file)

    root = tree.getroot()

    simulation = root.find("simulation")

    if simulation is None:
        raise RuntimeError(
            "Balise <simulation> introuvable."
        )

    ids = []

    for mote in simulation.findall("mote"):

        mote_id = get_mote_id(mote)

        if mote_id is not None:
            ids.append(mote_id)

    return ids


# ============================================================
# VALIDATION
# ============================================================

def validate_parameters(
    seed: int,
    imin: int,
    imax: int,
    k: int,
    tx_range: float,
    nb_nodes: int,
    send_interval: int,
    objective_function: str,
):
    """
    Vérifie les paramètres expérimentaux.
    """

    if seed < 0:
        raise ValueError(
            "La seed doit être positive ou nulle."
        )

    if imin < 0:
        raise ValueError(
            "Imin doit être positif ou nul."
        )

    if imax < imin:
        raise ValueError(
            f"Imax ({imax}) doit être >= Imin ({imin})."
        )

    if k < 0:
        raise ValueError(
            "k doit être positif ou nul."
        )

    if tx_range <= 0:
        raise ValueError(
            "tx_range doit être strictement positif."
        )

    if nb_nodes < 2:
        raise ValueError(
            "Le réseau doit contenir au moins 2 nœuds."
        )

    max_nodes = count_motes_in_csc(
        BASE_CSC_FILE
    )

    if nb_nodes > max_nodes:
        raise ValueError(
            f"Le fichier {BASE_CSC_FILE.name} contient "
            f"{max_nodes} nœuds, mais nb_nodes={nb_nodes} "
            f"a été demandé."
        )

    if send_interval <= 0:
        raise ValueError(
            "send_interval doit être strictement positif."
        )

    objective_function = (
        objective_function
        .strip()
        .upper()
    )

    if (
        objective_function
        not in SUPPORTED_OBJECTIVE_FUNCTIONS
    ):
        raise ValueError(
            f"Objective Function invalide : "
            f"{objective_function}. "
            "Valeurs autorisées : OF0, MRHOF."
        )


# ============================================================
# PROJECT-CONF.H
# ============================================================

def write_project_conf(
    *,
    imin: int,
    imax: int,
    k: int,
    send_interval: int,
    objective_function: str,
):
    """
    Génère project-conf.h.
    """

    objective_function = (
        objective_function
        .strip()
        .upper()
    )

    if (
        objective_function
        not in SUPPORTED_OBJECTIVE_FUNCTIONS
    ):
        raise ValueError(
            f"Objective Function non supportée : "
            f"{objective_function}"
        )

    doublings = (
        imax - imin
    )

    objective_macro = (
        SUPPORTED_OBJECTIVE_FUNCTIONS[
            objective_function
        ]
    )

    content = f"""\
#ifndef PROJECT_CONF_H_
#define PROJECT_CONF_H_

/* =========================================================
 * ENERGEST
 * ========================================================= */
#define ENERGEST_CONF_ON 1

/* =========================================================
 * RPL / TRICKLE
 * ========================================================= */
#define RPL_CONF_DIO_INTERVAL_MIN {imin}
#define RPL_CONF_DIO_INTERVAL_DOUBLINGS {doublings}
#define RPL_CONF_DIO_REDUNDANCY {k}

/* =========================================================
 * RPL OBJECTIVE FUNCTION
 * Tous les noeuds supportent OF0 et MRHOF.
 * Le root sélectionne l'OF utilisée.
 * ========================================================= */
#define RPL_CONF_SUPPORTED_OFS {{&rpl_of0, &rpl_mrhof}}
#define RPL_CONF_OF_OCP {objective_macro}

/* =========================================================
 * APPLICATION
 * Valeur en secondes
 * ========================================================= */
#define APP_CONF_SEND_INTERVAL {send_interval}

#endif /* PROJECT_CONF_H_ */
"""

    PROJECT_CONF_FILE.write_text(
        content,
        encoding="utf-8",
    )


# ============================================================
# CREATION DU CSC TEMPORAIRE
# ============================================================

def create_experiment_csc(
    *,
    output_file: Path,
    seed: int,
    tx_range: float,
    nb_nodes: int,
):
    """
    Crée un .csc spécifique au run.

    Modifie :
      - randomseed
      - transmitting_range
      - nombre de motes

    Le simulation_rpl.csc original n'est pas modifié.
    """

    if not BASE_CSC_FILE.exists():
        raise FileNotFoundError(
            f"Fichier introuvable : {BASE_CSC_FILE}"
        )

    tree = ET.parse(
        BASE_CSC_FILE
    )

    root = tree.getroot()

    simulation = root.find(
        "simulation"
    )

    if simulation is None:
        raise RuntimeError(
            "Balise <simulation> introuvable."
        )

    # --------------------------------------------------------
    # RANDOM SEED
    # --------------------------------------------------------

    randomseed = simulation.find(
        "randomseed"
    )

    if randomseed is None:

        randomseed = ET.Element(
            "randomseed"
        )

        simulation.insert(
            1,
            randomseed,
        )

    randomseed.text = str(
        int(seed)
    )

    # --------------------------------------------------------
    # RADIO MEDIUM
    # --------------------------------------------------------

    radio_medium = simulation.find(
        "radiomedium"
    )

    if radio_medium is None:
        raise RuntimeError(
            "Balise <radiomedium> introuvable."
        )

    transmitting_range = (
        radio_medium.find(
            "transmitting_range"
        )
    )

    if transmitting_range is None:
        raise RuntimeError(
            "Balise <transmitting_range> introuvable."
        )

    transmitting_range.text = str(
        float(tx_range)
    )

    # --------------------------------------------------------
    # MOTES
    # --------------------------------------------------------

    motes = simulation.findall(
        "mote"
    )

    available_nodes = len(
        motes
    )

    if nb_nodes > available_nodes:
        raise ValueError(
            f"{nb_nodes} nœuds demandés mais "
            f"{available_nodes} seulement sont disponibles."
        )

    # --------------------------------------------------------
    # On suppose que les motes sont ordonnés :
    #
    # ID 1
    # ID 2
    # ...
    # ID 20
    #
    # On conserve donc les nb_nodes premiers.
    # --------------------------------------------------------

    for mote in motes[
        nb_nodes:
    ]:
        simulation.remove(
            mote
        )

    # --------------------------------------------------------
    # PLUGIN TIMELINE
    # --------------------------------------------------------
    #
    # TimeLine utilise des indices 0-based.
    #
    # 0 -> node 1
    # 1 -> node 2
    # ...
    #
    # --------------------------------------------------------

    for plugin in root.findall(
        "plugin"
    ):

        plugin_name = (
            plugin.text or ""
        )

        if "TimeLine" not in plugin_name:
            continue

        plugin_config = plugin.find(
            "plugin_config"
        )

        if plugin_config is None:
            continue

        timeline_motes = (
            plugin_config.findall(
                "mote"
            )
        )

        for mote_element in timeline_motes:

            try:
                mote_index = int(
                    mote_element.text
                )

            except (
                TypeError,
                ValueError,
            ):
                continue

            if mote_index >= nb_nodes:
                plugin_config.remove(
                    mote_element
                )

    # --------------------------------------------------------
    # DOSSIER
    # --------------------------------------------------------

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # WRITE
    # --------------------------------------------------------

    tree.write(
        output_file,
        encoding="UTF-8",
        xml_declaration=True,
    )


# ============================================================
# CLEAN BUILD
# ============================================================

def clean_cooja_build():
    """
    Nettoie les fichiers compilés Cooja
    de l'application rpl-udp.
    """

    build_dir = (
        RPL_UDP_DIR
        / "build"
        / "cooja"
    )

    if build_dir.exists():
        shutil.rmtree(
            build_dir
        )


# ============================================================
# LANCEMENT COOJA
# ============================================================

def launch_cooja(
    *,
    csc_file: Path,
    run_directory: Path,
) -> Path:
    """
    Lance Cooja headless.

    Cooja crée COOJA.testlog dans COOJA_DIR.
    Ce fichier est ensuite déplacé dans le dossier du run.

    Cela évite de mélanger les logs des différentes
    simulations.
    """

    cooja_log = (
        COOJA_DIR
        / "COOJA.testlog"
    )

    run_log = (
        run_directory
        / "COOJA.testlog"
    )

    # --------------------------------------------------------
    # SUPPRIMER LES ANCIENS LOGS
    # --------------------------------------------------------

    if cooja_log.exists():
        cooja_log.unlink()

    if run_log.exists():
        run_log.unlink()

    # --------------------------------------------------------
    # COMMANDE
    # --------------------------------------------------------

    command = [
        "./gradlew",
        "run",
        f"--args=--no-gui {csc_file}",
    ]

    # --------------------------------------------------------
    # COOJA
    # --------------------------------------------------------

    subprocess.run(
        command,
        cwd=COOJA_DIR,
        check=True,
    )

    # --------------------------------------------------------
    # VERIFICATION LOG
    # --------------------------------------------------------

    if not cooja_log.exists():

        raise FileNotFoundError(
            "Cooja a terminé mais "
            f"{cooja_log} n'existe pas."
        )

    # --------------------------------------------------------
    # DEPLACEMENT
    # --------------------------------------------------------

    shutil.move(
        str(cooja_log),
        str(run_log),
    )

    return run_log


# ============================================================
# SUMMARY
# ============================================================

def count_summary_lines(
    log_file: Path,
) -> int:
    """
    Compte les lignes SUMMARY.
    """

    count = 0

    with log_file.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as file:

        for line in file:

            if "SUMMARY" in line:
                count += 1

    return count


# ============================================================
# RUN SIMULATION
# ============================================================

def run_simulation(
    *,
    seed: int,
    imin: int,
    imax: int,
    k: int,
    tx_range: float,
    nb_nodes: int,
    send_interval: int,
    objective_function: str = "MRHOF",
    run_name: str = "test_run",
    clean_build: bool = True,
) -> Path:
    """
    Lance une simulation Cooja complète.

    Retourne le chemin vers COOJA.testlog.
    """

    objective_function = (
        objective_function
        .strip()
        .upper()
    )

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    validate_parameters(
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
    )

    max_nodes = (
        count_motes_in_csc(
            BASE_CSC_FILE
        )
    )

    # --------------------------------------------------------
    # RUN DIRECTORY
    # --------------------------------------------------------

    run_directory = (
        LOGS_DIR
        / run_name
    )

    run_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    csc_file = (
        run_directory
        / "simulation.csc"
    )

    # --------------------------------------------------------
    # AFFICHAGE
    # --------------------------------------------------------

    print()
    print("=" * 75)

    print(
        f"RUN           : {run_name}"
    )

    print(
        f"Seed          : {seed}"
    )

    print(
        f"Imin          : {imin}"
    )

    print(
        f"Imax          : {imax}"
    )

    print(
        f"Doublings     : {imax - imin}"
    )

    print(
        f"k             : {k}"
    )

    print(
        f"Objective Fn  : {objective_function}"
    )

    print(
        f"TX Range      : {tx_range}"
    )

    print(
        f"Nb nodes      : {nb_nodes}"
    )

    print(
        f"Max CSC nodes : {max_nodes}"
    )

    print(
        f"Send interval : {send_interval}s"
    )

    print("=" * 75)

    # --------------------------------------------------------
    # PROJECT CONF
    # --------------------------------------------------------

    write_project_conf(
        imin=imin,
        imax=imax,
        k=k,
        send_interval=send_interval,
        objective_function=(
            objective_function
        ),
    )

    # --------------------------------------------------------
    # CSC
    # --------------------------------------------------------

    create_experiment_csc(
        output_file=csc_file,
        seed=seed,
        tx_range=tx_range,
        nb_nodes=nb_nodes,
    )

    # --------------------------------------------------------
    # Vérification seed du fichier généré
    # --------------------------------------------------------

    check_tree = ET.parse(
        csc_file
    )

    check_simulation = (
        check_tree
        .getroot()
        .find(
            "simulation"
        )
    )

    written_seed = None

    if check_simulation is not None:

        randomseed = (
            check_simulation.find(
                "randomseed"
            )
        )

        if randomseed is not None:
            written_seed = (
                randomseed.text
            )

    if written_seed != str(seed):

        raise RuntimeError(
            f"Seed incorrecte dans le CSC : "
            f"attendu={seed}, "
            f"trouvé={written_seed}"
        )

    # --------------------------------------------------------
    # CLEAN
    # --------------------------------------------------------

    if clean_build:
        clean_cooja_build()

    # --------------------------------------------------------
    # RUN COOJA
    # --------------------------------------------------------

    log_file = launch_cooja(
        csc_file=csc_file,
        run_directory=run_directory,
    )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    summary_count = (
        count_summary_lines(
            log_file
        )
    )

    if summary_count == 0:

        raise RuntimeError(
            f"Aucun SUMMARY trouvé dans "
            f"{log_file}"
        )

    print(
        f"[OK] {run_name} terminé "
        f"({summary_count} SUMMARY)"
    )

    return log_file


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print()
    print(
        "Vérification automatique du "
        "fichier simulation_rpl.csc"
    )

    print(
        f"CSC : {BASE_CSC_FILE}"
    )

    print(
        "Motes détectés :",
        count_motes_in_csc(
            BASE_CSC_FILE
        ),
    )

    print(
        "IDs détectés :",
        get_mote_ids_from_csc(
            BASE_CSC_FILE
        ),
    )

    # --------------------------------------------------------
    # TEST 20 NODES
    # --------------------------------------------------------

    log = run_simulation(
        seed=1,
        imin=10,
        imax=18,
        k=5,
        tx_range=50.0,
        nb_nodes=20,
        send_interval=10,
        objective_function="MRHOF",
        run_name="test_20_nodes",
        clean_build=True,
    )

    print(
        f"\nLog : {log}"
    )