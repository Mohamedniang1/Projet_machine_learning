#!/usr/bin/env python3

import argparse
from pathlib import Path

import pandas as pd


# ============================================================
# CONFIGURATION EXPERIMENTALE
# ============================================================

CONFIG_COLUMNS = [
    "run_name",
    "seed",
    "imin",
    "imax",
    "k",
    "tx_range",
    "nb_nodes",
    "send_interval",
    "objective_function",
]

CONFIG_PARAMETERS = [
    "seed",
    "imin",
    "imax",
    "k",
    "tx_range",
    "nb_nodes",
    "send_interval",
    "objective_function",
]


# ============================================================
# MODELE ENERGETIQUE DE REFERENCE
# ============================================================
#
# Plateforme de référence :
#     Tmote Sky / TelosB
#
# MCU :
#     MSP430F1611
#
# Radio :
#     CC2420
#
# IMPORTANT :
# Ces valeurs permettent une ESTIMATION énergétique.
# Elles ne constituent pas une mesure physique réelle
# de l'énergie consommée par Cooja.
#
# ============================================================

REFERENCE_VOLTAGE_V = 3.0

CPU_CURRENT_MA = 0.5

LPM_CURRENT_MA = 0.0026

RADIO_TX_CURRENT_MA = 17.4

RADIO_RX_CURRENT_MA = 18.8


# ============================================================
# ENERGEST
# ============================================================
#
# Pour la plateforme Cooja :
#
# RTIMER_ARCH_SECOND = 1 000 000
#
# et :
#
# ENERGEST_SECOND = RTIMER_SECOND
#
# Donc :
#
# 1 seconde = 1 000 000 ticks
#
# ============================================================

ENERGEST_SECOND = 1_000_000.0


# ============================================================
# METRIQUES A AGREGER
# ============================================================

METRIC_COLUMNS = [
    "pdr_global",
    "pdr_window",

    "delay_avg_ms",

    "rssi_avg",

    "etx",

    "rank",
    "parent_rank",
    "neighbors",

    "radio_tx_ticks",
    "radio_listen_ticks",

    "radio_tx_percent",
    "radio_listen_percent",

    # Energie
    "energy_cpu_mj",
    "energy_lpm_mj",
    "energy_radio_tx_mj",
    "energy_radio_rx_mj",
    "energy_estimated_mj",
]


# ============================================================
# ARGUMENTS
# ============================================================

def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Agrège le dataset détaillé Cooja "
            "afin d'obtenir une ligne par simulation."
        )
    )

    parser.add_argument(
        "--input",
        default="cooja_automation/dataset.csv",
        help="Dataset détaillé produit par parse_log.py",
    )

    parser.add_argument(
        "--output",
        default="cooja_automation/dataset_runs.csv",
        help="Dataset agrégé : une ligne par run",
    )

    return parser.parse_args()


# ============================================================
# ACTIVITE RADIO
# ============================================================

def add_radio_activity_metrics(df: pd.DataFrame) -> pd.DataFrame:

    required_columns = [
        "radio_tx_ticks",
        "radio_listen_ticks",
        "total_time_ticks",
    ]

    missing = [
        col
        for col in required_columns
        if col not in df.columns
    ]

    if missing:

        raise ValueError(
            "Impossible de calculer les métriques radio. "
            "Colonnes manquantes : "
            + ", ".join(missing)
        )

    for col in required_columns:

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce",
        )

    valid_time = (
        df["total_time_ticks"].notna()
        &
        (df["total_time_ticks"] > 0)
    )

    df["radio_tx_percent"] = float("nan")
    df["radio_listen_percent"] = float("nan")

    df.loc[
        valid_time,
        "radio_tx_percent"
    ] = (
        df.loc[
            valid_time,
            "radio_tx_ticks"
        ]
        /
        df.loc[
            valid_time,
            "total_time_ticks"
        ]
        * 100.0
    )

    df.loc[
        valid_time,
        "radio_listen_percent"
    ] = (
        df.loc[
            valid_time,
            "radio_listen_ticks"
        ]
        /
        df.loc[
            valid_time,
            "total_time_ticks"
        ]
        * 100.0
    )

    print(
        "\n[OK] Indicateurs radio calculés :"
    )

    print(
        "  - radio_tx_percent"
    )

    print(
        "  - radio_listen_percent"
    )

    return df


# ============================================================
# CALCUL ENERGETIQUE
# ============================================================

def add_energy_metrics(df: pd.DataFrame) -> pd.DataFrame:

    """
    Calcule une estimation énergétique en millijoules.

    Formule générale :

        E = V * I * t

    Avec :
        V en volts
        I en ampères
        t en secondes

    Le résultat initial est en joules.

    On multiplie ensuite par 1000 pour obtenir des mJ.

    L'énergie totale estimée correspond à :

        E_CPU
        + E_LPM
        + E_RADIO_TX
        + E_RADIO_RX

    CPU et radio sont additionnés car ils représentent
    deux composants matériels distincts pouvant être actifs
    simultanément.
    """

    required_columns = [
        "cpu_ticks",
        "lpm_ticks",
        "deep_lpm_ticks",
        "radio_tx_ticks",
        "radio_listen_ticks",
    ]

    missing = [
        col
        for col in required_columns
        if col not in df.columns
    ]

    if missing:

        raise ValueError(
            "Impossible de calculer l'énergie. "
            "Colonnes Energest manquantes : "
            + ", ".join(missing)
        )

    for col in required_columns:

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce",
        )

    # --------------------------------------------------------
    # Vérification Deep LPM
    # --------------------------------------------------------
    #
    # Nous n'attribuons pas de courant arbitraire au
    # Deep LPM.
    #
    # Dans les simulations actuelles Cooja, deep_lpm_ticks
    # est nul.
    #
    # Si ce n'est plus le cas plus tard, on arrête le script
    # afin de ne pas produire une estimation fausse.
    # --------------------------------------------------------

    non_zero_deep_lpm = (
        df["deep_lpm_ticks"].fillna(0) > 0
    ).sum()

    if non_zero_deep_lpm > 0:

        raise ValueError(
            "deep_lpm_ticks contient des valeurs > 0. "
            "Le modèle énergétique actuel ne définit pas "
            "de courant Deep LPM. "
            "Il faut ajouter une valeur matérielle documentée "
            "avant de continuer."
        )

    # --------------------------------------------------------
    # Conversion ticks -> secondes
    # --------------------------------------------------------

    cpu_seconds = (
        df["cpu_ticks"]
        / ENERGEST_SECOND
    )

    lpm_seconds = (
        df["lpm_ticks"]
        / ENERGEST_SECOND
    )

    tx_seconds = (
        df["radio_tx_ticks"]
        / ENERGEST_SECOND
    )

    rx_seconds = (
        df["radio_listen_ticks"]
        / ENERGEST_SECOND
    )

    # --------------------------------------------------------
    # Conversion mA -> A
    # --------------------------------------------------------

    cpu_current_a = (
        CPU_CURRENT_MA / 1000.0
    )

    lpm_current_a = (
        LPM_CURRENT_MA / 1000.0
    )

    tx_current_a = (
        RADIO_TX_CURRENT_MA / 1000.0
    )

    rx_current_a = (
        RADIO_RX_CURRENT_MA / 1000.0
    )

    # --------------------------------------------------------
    # Energie en Joules
    # --------------------------------------------------------

    energy_cpu_j = (
        REFERENCE_VOLTAGE_V
        * cpu_current_a
        * cpu_seconds
    )

    energy_lpm_j = (
        REFERENCE_VOLTAGE_V
        * lpm_current_a
        * lpm_seconds
    )

    energy_tx_j = (
        REFERENCE_VOLTAGE_V
        * tx_current_a
        * tx_seconds
    )

    energy_rx_j = (
        REFERENCE_VOLTAGE_V
        * rx_current_a
        * rx_seconds
    )

    # --------------------------------------------------------
    # Joules -> millijoules
    # --------------------------------------------------------

    df["energy_cpu_mj"] = (
        energy_cpu_j * 1000.0
    )

    df["energy_lpm_mj"] = (
        energy_lpm_j * 1000.0
    )

    df["energy_radio_tx_mj"] = (
        energy_tx_j * 1000.0
    )

    df["energy_radio_rx_mj"] = (
        energy_rx_j * 1000.0
    )

    # --------------------------------------------------------
    # Energie totale estimée
    # --------------------------------------------------------

    df["energy_estimated_mj"] = (
        df["energy_cpu_mj"]
        + df["energy_lpm_mj"]
        + df["energy_radio_tx_mj"]
        + df["energy_radio_rx_mj"]
    )

    print(
        "\n[OK] Estimation énergétique calculée :"
    )

    print(
        "  - energy_cpu_mj"
    )

    print(
        "  - energy_lpm_mj"
    )

    print(
        "  - energy_radio_tx_mj"
    )

    print(
        "  - energy_radio_rx_mj"
    )

    print(
        "  - energy_estimated_mj"
    )

    print(
        "\nModèle énergétique :"
    )

    print(
        f"  Voltage     : "
        f"{REFERENCE_VOLTAGE_V} V"
    )

    print(
        f"  CPU current : "
        f"{CPU_CURRENT_MA} mA"
    )

    print(
        f"  LPM current : "
        f"{LPM_CURRENT_MA} mA"
    )

    print(
        f"  TX current  : "
        f"{RADIO_TX_CURRENT_MA} mA"
    )

    print(
        f"  RX current  : "
        f"{RADIO_RX_CURRENT_MA} mA"
    )

    print(
        f"  Energest Hz : "
        f"{ENERGEST_SECOND:.0f}"
    )

    return df


# ============================================================
# VALIDATION DES CONFIGURATIONS
# ============================================================

def validate_run_configurations(df: pd.DataFrame) -> None:

    print(
        "\nVérification des paramètres de configuration..."
    )

    problem_found = False

    for col in CONFIG_PARAMETERS:

        counts = (
            df.groupby(
                "run_name"
            )[col]
            .nunique(
                dropna=False
            )
        )

        invalid = (
            counts[
                counts > 1
            ]
        )

        if len(invalid) > 0:

            problem_found = True

            print(
                f"[ATTENTION] "
                f"{col} varie dans "
                f"{len(invalid)} run(s)"
            )

    if not problem_found:

        print(
            "[OK] Chaque run possède "
            "une configuration cohérente."
        )


# ============================================================
# MAIN
# ============================================================

def main():

    args = parse_args()

    input_path = Path(
        args.input
    )

    output_path = Path(
        args.output
    )

    if not input_path.exists():

        raise FileNotFoundError(
            f"Dataset introuvable : "
            f"{input_path}"
        )

    df = pd.read_csv(
        input_path
    )

    print("=" * 70)
    print("CONSTRUCTION DU DATASET PAR RUN")
    print("=" * 70)

    print(
        f"\nDataset source : "
        f"{input_path}"
    )

    print(
        f"Nombre de lignes : "
        f"{len(df)}"
    )

    if "run_name" not in df.columns:

        raise ValueError(
            "La colonne 'run_name' "
            "est absente du dataset."
        )

    print(
        f"Nombre de runs : "
        f"{df['run_name'].nunique()}"
    )

    # --------------------------------------------------------
    # Vérification configuration
    # --------------------------------------------------------

    missing_config = [
        col
        for col in CONFIG_COLUMNS
        if col not in df.columns
    ]

    if missing_config:

        raise ValueError(
            "Colonnes de configuration manquantes : "
            + ", ".join(missing_config)
        )

    # --------------------------------------------------------
    # Objective Function
    # --------------------------------------------------------

    df["objective_function"] = (
        df["objective_function"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    allowed_of = {
        "OF0",
        "MRHOF",
    }

    invalid_of = (
        ~df[
            "objective_function"
        ].isin(
            allowed_of
        )
    )

    if invalid_of.any():

        raise ValueError(
            "Objective Function invalide détectée."
        )

    print(
        "\n[OK] Objective Functions valides."
    )

    # --------------------------------------------------------
    # Cohérence runs
    # --------------------------------------------------------

    validate_run_configurations(
        df
    )

    # --------------------------------------------------------
    # Radio
    # --------------------------------------------------------

    df = add_radio_activity_metrics(
        df
    )

    # --------------------------------------------------------
    # Energie
    # --------------------------------------------------------

    df = add_energy_metrics(
        df
    )

    # --------------------------------------------------------
    # Métriques disponibles
    # --------------------------------------------------------

    available_metrics = [
        col
        for col in METRIC_COLUMNS
        if col in df.columns
    ]

    missing_metrics = [
        col
        for col in METRIC_COLUMNS
        if col not in df.columns
    ]

    print(
        "\nMétriques utilisées :"
    )

    for col in available_metrics:

        print(
            f"  - {col}"
        )

    if missing_metrics:

        print(
            "\nMétriques absentes :"
        )

        for col in missing_metrics:

            print(
                f"  - {col}"
            )

    # --------------------------------------------------------
    # Conversion numérique
    # --------------------------------------------------------

    for col in available_metrics:

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce",
        )

    # --------------------------------------------------------
    # Valeurs manquantes
    # --------------------------------------------------------

    missing_values = (
        df[
            available_metrics
        ]
        .isna()
        .sum()
    )

    missing_values = (
        missing_values[
            missing_values > 0
        ]
    )

    print(
        "\nValeurs manquantes "
        "dans les métriques :"
    )

    if len(missing_values) == 0:

        print(
            "[OK] Aucune valeur manquante."
        )

    else:

        print(
            missing_values
        )

        raise ValueError(
            "Certaines métriques contiennent "
            "des valeurs manquantes."
        )

    # --------------------------------------------------------
    # Agrégation
    # --------------------------------------------------------

    aggregation = {}

    for col in CONFIG_PARAMETERS:

        aggregation[col] = "first"

    for col in available_metrics:

        aggregation[col] = [
            "mean",
            "std",
            "min",
            "max",
        ]

    grouped = (
        df.groupby(
            "run_name",
            as_index=False
        )
        .agg(
            aggregation
        )
    )

    # --------------------------------------------------------
    # Aplatir MultiIndex
    # --------------------------------------------------------

    new_columns = []

    for col in grouped.columns:

        if isinstance(
            col,
            tuple
        ):

            base = col[0]
            stat = col[1]

            if stat in (
                "",
                "first",
            ):

                new_columns.append(
                    base
                )

            else:

                new_columns.append(
                    f"{base}_{stat}"
                )

        else:

            new_columns.append(
                col
            )

    grouped.columns = (
        new_columns
    )

    # --------------------------------------------------------
    # n_samples
    # --------------------------------------------------------

    samples_per_run = (
        df.groupby(
            "run_name"
        )
        .size()
        .rename(
            "n_samples"
        )
        .reset_index()
    )

    grouped = grouped.merge(
        samples_per_run,
        on="run_name",
        how="left",
    )

    # --------------------------------------------------------
    # Nœuds observés
    # --------------------------------------------------------

    if "node" in df.columns:

        observed_nodes = (
            df.groupby(
                "run_name"
            )["node"]
            .nunique()
            .rename(
                "n_observed_nodes"
            )
            .reset_index()
        )

        grouped = grouped.merge(
            observed_nodes,
            on="run_name",
            how="left",
        )

    # --------------------------------------------------------
    # Organisation colonnes
    # --------------------------------------------------------

    first_columns = [
        col
        for col in CONFIG_COLUMNS
        if col in grouped.columns
    ]

    extra_columns = [
        "n_samples",
        "n_observed_nodes",
    ]

    extra_columns = [
        col
        for col in extra_columns
        if col in grouped.columns
    ]

    remaining_columns = [
        col
        for col in grouped.columns
        if col not in first_columns
        and col not in extra_columns
    ]

    grouped = grouped[
        first_columns
        + extra_columns
        + remaining_columns
    ]

    # --------------------------------------------------------
    # Sauvegarde
    # --------------------------------------------------------

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    grouped.to_csv(
        output_path,
        index=False,
    )

    # --------------------------------------------------------
    # Résumé
    # --------------------------------------------------------

    print(
        "\n" + "=" * 70
    )

    print(
        "RÉSULTAT"
    )

    print(
        "=" * 70
    )

    print(
        f"\nNombre de runs source : "
        f"{df['run_name'].nunique()}"
    )

    print(
        f"Nombre de lignes finales : "
        f"{len(grouped)}"
    )

    print(
        f"Nombre de colonnes : "
        f"{len(grouped.columns)}"
    )

    print(
        f"\nDataset créé : "
        f"{output_path}"
    )

    preview_columns = [
        "run_name",
        "objective_function",
        "pdr_window_mean",
        "delay_avg_ms_mean",
        "rssi_avg_mean",
        "etx_mean",
        "radio_tx_percent_mean",
        "energy_estimated_mj_mean",
    ]

    preview_columns = [
        col
        for col in preview_columns
        if col in grouped.columns
    ]

    print(
        "\nAperçu :\n"
    )

    print(
        grouped[
            preview_columns
        ].to_string(
            index=False
        )
    )

    print(
        "\nEnergy estimated statistics :"
    )

    print(
        grouped[
            "energy_estimated_mj_mean"
        ].describe()
    )

    print(
        "\n[OK] Agrégation terminée."
    )


if __name__ == "__main__":
    main()