from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONTIKI_DIR = PROJECT_ROOT / "contiki-ng"
COOJA_DIR = CONTIKI_DIR / "tools" / "cooja"
RPL_UDP_DIR = CONTIKI_DIR / "examples" / "rpl-udp"

BASE_CSC_FILE = RPL_UDP_DIR / "simulation_rpl.csc"
PROJECT_CONF_FILE = RPL_UDP_DIR / "project-conf.h"

LOGS_DIR = PROJECT_ROOT / "cooja_automation" / "logs"


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
):
    if seed < 0:
        raise ValueError("seed doit être >= 0")

    if imin < 1:
        raise ValueError("Imin doit être >= 1")

    if imax < imin:
        raise ValueError("Imax doit être >= Imin")

    if k < 0:
        raise ValueError("k doit être >= 0")

    if tx_range <= 0:
        raise ValueError("tx_range doit être > 0")

    if nb_nodes < 2:
        raise ValueError(
            "Il faut au minimum 2 nœuds : 1 root + 1 client"
        )

    if nb_nodes > 16:
        raise ValueError(
            "Le simulation_rpl.csc actuel contient seulement 16 nœuds."
        )

    if send_interval <= 0:
        raise ValueError("send_interval doit être > 0")


# ============================================================
# PROJECT-CONF.H
# ============================================================

def write_project_conf(
    *,
    imin: int,
    imax: int,
    k: int,
    send_interval: int,
):
    """
    Génère la configuration compilée par Contiki-NG.
    """

    doublings = imax - imin

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
# GÉNÉRATION DU .CSC TEMPORAIRE
# ============================================================

def create_experiment_csc(
    *,
    output_file: Path,
    tx_range: float,
    nb_nodes: int,
):
    """
    Copie simulation_rpl.csc et modifie :

    - transmitting_range
    - nombre de motes

    Le fichier original n'est jamais modifié.
    """

    tree = ET.parse(BASE_CSC_FILE)
    root = tree.getroot()

    simulation = root.find("simulation")

    if simulation is None:
        raise RuntimeError(
            "Balise <simulation> introuvable dans le .csc"
        )

    # --------------------------------------------------------
    # TX RANGE
    # --------------------------------------------------------

    radio = simulation.find("radiomedium")

    if radio is None:
        raise RuntimeError(
            "Balise <radiomedium> introuvable"
        )

    tx_element = radio.find("transmitting_range")

    if tx_element is None:
        raise RuntimeError(
            "<transmitting_range> introuvable"
        )

    tx_element.text = str(float(tx_range))

    # --------------------------------------------------------
    # NOMBRE DE NŒUDS
    # --------------------------------------------------------

    motes = simulation.findall("mote")

    if len(motes) < nb_nodes:
        raise RuntimeError(
            f"Seulement {len(motes)} motes disponibles, "
            f"mais {nb_nodes} demandés."
        )

    # On garde :
    # mote 1 = root
    # puis les premiers clients jusqu'à nb_nodes
    for mote in motes[nb_nodes:]:
        simulation.remove(mote)

    tree.write(
        output_file,
        encoding="UTF-8",
        xml_declaration=True,
    )


# ============================================================
# SIMULATION
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
    run_name: str,
    clean_build: bool = True,
) -> Path:

    validate_parameters(
        seed,
        imin,
        imax,
        k,
        tx_range,
        nb_nodes,
        send_interval,
    )

    LOGS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    run_dir = LOGS_DIR / run_name

    if run_dir.exists():
        shutil.rmtree(run_dir)

    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Configuration Contiki
    # --------------------------------------------------------

    write_project_conf(
        imin=imin,
        imax=imax,
        k=k,
        send_interval=send_interval,
    )

    # --------------------------------------------------------
    # Configuration Cooja
    # --------------------------------------------------------

    experiment_csc = run_dir / "simulation.csc"

    create_experiment_csc(
        output_file=experiment_csc,
        tx_range=tx_range,
        nb_nodes=nb_nodes,
    )

    # --------------------------------------------------------
    # IMPORTANT :
    # project-conf.h a changé -> recompilation
    # --------------------------------------------------------

    if clean_build:
        build_dir = RPL_UDP_DIR / "build"

        if build_dir.exists():
            shutil.rmtree(build_dir)

    doublings = imax - imin

    print("\n" + "=" * 75)
    print(f"RUN           : {run_name}")
    print(f"Seed          : {seed}")
    print(f"Imin          : {imin}")
    print(f"Imax          : {imax}")
    print(f"Doublings     : {doublings}")
    print(f"k             : {k}")
    print(f"TX Range      : {tx_range}")
    print(f"Nb nodes      : {nb_nodes}")
    print(f"Send interval : {send_interval}s")
    print("=" * 75)

    cooja_args = " ".join(
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
        str(COOJA_DIR / "gradlew"),
        "run",
        f"--args={cooja_args}",
    ]

    result = subprocess.run(
        command,
        cwd=COOJA_DIR,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Cooja a échoué : code {result.returncode}"
        )

    testlog = run_dir / "COOJA.testlog"

    if not testlog.exists():
        raise FileNotFoundError(
            f"COOJA.testlog absent pour {run_name}"
        )

    summary_count = 0

    with testlog.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as f:
        for line in f:
            if "SUMMARY," in line:
                summary_count += 1

    if summary_count == 0:
        raise RuntimeError(
            f"Aucun SUMMARY pour {run_name}"
        )

    print(
        f"[OK] {run_name} terminé "
        f"({summary_count} SUMMARY)"
    )

    return testlog


# ============================================================
# TEST DIRECT
# ============================================================

if __name__ == "__main__":

    log = run_simulation(
        seed=1,
        imin=10,
        imax=18,
        k=5,
        tx_range=50.0,
        nb_nodes=12,
        send_interval=10,
        run_name="test_new_parameters",
        clean_build=True,
    )

    print(f"\nLog : {log}")