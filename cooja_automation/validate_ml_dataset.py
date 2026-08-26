#!/usr/bin/env python3

from pathlib import Path
import sys

import pandas as pd


INPUT_FILE = Path(
    "cooja_automation/dataset_ml_ready.csv"
)


EXPECTED_COLUMNS = [
    "run_name",
    "seed",

    "imin",
    "imax",
    "k",
    "tx_range",
    "nb_nodes",
    "send_interval",
    "objective_function",

    "n_samples",

    "pdr_window_mean",
    "delay_avg_ms_mean",
    "rssi_avg_mean",
    "etx_mean",
    "radio_tx_percent_mean",
    "energy_estimated_mj_mean",
    "energy_radio_tx_mj_mean",
]


FEATURE_COLUMNS = [
    "imin",
    "imax",
    "k",
    "tx_range",
    "nb_nodes",
    "send_interval",
    "objective_function",
]


TARGET_COLUMNS = [
    "pdr_window_mean",
    "delay_avg_ms_mean",
    "rssi_avg_mean",
    "etx_mean",
    "radio_tx_percent_mean",
    "energy_estimated_mj_mean",
    "energy_radio_tx_mj_mean",
]


def ok(message):
    print(f"[OK] {message}")


def error(message):
    print(f"[ERROR] {message}")


def warning(message):
    print(f"[WARNING] {message}")


def main():

    print("=" * 70)
    print("VALIDATION DU DATASET ML")
    print("=" * 70)

    errors = []
    warnings = []

    if not INPUT_FILE.exists():

        error(
            f"Fichier introuvable : "
            f"{INPUT_FILE}"
        )

        sys.exit(1)

    df = pd.read_csv(
        INPUT_FILE
    )

    ok(
        f"Dataset chargé : "
        f"{len(df)} lignes, "
        f"{len(df.columns)} colonnes"
    )

    # --------------------------------------------------------
    # Colonnes
    # --------------------------------------------------------

    missing_columns = [
        col
        for col in EXPECTED_COLUMNS
        if col not in df.columns
    ]

    unexpected_columns = [
        col
        for col in df.columns
        if col not in EXPECTED_COLUMNS
    ]

    if missing_columns:

        msg = (
            "Colonnes manquantes : "
            + ", ".join(missing_columns)
        )

        error(msg)
        errors.append(msg)

    else:

        ok(
            "Toutes les colonnes attendues "
            "sont présentes"
        )

    if unexpected_columns:

        msg = (
            "Colonnes inattendues : "
            + ", ".join(unexpected_columns)
        )

        warning(msg)
        warnings.append(msg)

    else:

        ok(
            "Aucune colonne inattendue"
        )

    if missing_columns:

        sys.exit(1)

    # --------------------------------------------------------
    # Missing
    # --------------------------------------------------------

    total_missing = int(
        df.isna().sum().sum()
    )

    if total_missing == 0:

        ok(
            "Aucune valeur manquante"
        )

    else:

        msg = (
            f"{total_missing} valeur(s) "
            "manquante(s)"
        )

        error(msg)
        errors.append(msg)

    # --------------------------------------------------------
    # Doublons
    # --------------------------------------------------------

    duplicate_count = int(
        df.duplicated().sum()
    )

    if duplicate_count == 0:

        ok(
            "Aucun doublon exact"
        )

    else:

        msg = (
            f"{duplicate_count} doublon(s)"
        )

        error(msg)
        errors.append(msg)

    duplicate_runs = int(
        df[
            "run_name"
        ]
        .duplicated()
        .sum()
    )

    if duplicate_runs == 0:

        ok(
            "Chaque run_name est unique"
        )

    else:

        msg = (
            f"{duplicate_runs} "
            "run_name dupliqué(s)"
        )

        error(msg)
        errors.append(msg)

    # --------------------------------------------------------
    # Objective Function
    # --------------------------------------------------------

    df[
        "objective_function"
    ] = (
        df[
            "objective_function"
        ]
        .astype(str)
        .str.upper()
    )

    invalid_of = (
        ~df[
            "objective_function"
        ].isin(
            {
                "OF0",
                "MRHOF",
            }
        )
    ).sum()

    if invalid_of == 0:

        ok(
            "Objective Functions valides "
            "(OF0 / MRHOF)"
        )

    else:

        msg = (
            f"{invalid_of} Objective "
            "Function(s) invalide(s)"
        )

        error(msg)
        errors.append(msg)

    # --------------------------------------------------------
    # Valeurs numériques
    # --------------------------------------------------------

    numeric_columns = [
        "seed",
        "imin",
        "imax",
        "k",
        "tx_range",
        "nb_nodes",
        "send_interval",
        "n_samples",
    ] + TARGET_COLUMNS

    for col in numeric_columns:

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce",
        )

    # --------------------------------------------------------
    # Trickle
    # --------------------------------------------------------

    invalid_trickle = (
        df["imax"]
        <
        df["imin"]
    ).sum()

    if invalid_trickle == 0:

        ok(
            "Cohérence Imin / Imax valide"
        )

    else:

        msg = (
            f"{invalid_trickle} ligne(s) "
            "avec Imax < Imin"
        )

        error(msg)
        errors.append(msg)

    # --------------------------------------------------------
    # PDR
    # --------------------------------------------------------

    invalid_pdr = (
        (
            df[
                "pdr_window_mean"
            ] < 0
        )
        |
        (
            df[
                "pdr_window_mean"
            ] > 100
        )
    ).sum()

    if invalid_pdr == 0:

        ok(
            "PDR dans [0,100]"
        )

    else:

        msg = (
            f"{invalid_pdr} PDR invalide(s)"
        )

        error(msg)
        errors.append(msg)

    # --------------------------------------------------------
    # Delay
    # --------------------------------------------------------

    invalid_delay = (
        df[
            "delay_avg_ms_mean"
        ] < 0
    ).sum()

    if invalid_delay == 0:

        ok(
            "Delay valide"
        )

    else:

        msg = (
            f"{invalid_delay} délai(s) invalide(s)"
        )

        error(msg)
        errors.append(msg)

    # --------------------------------------------------------
    # ETX
    # --------------------------------------------------------

    invalid_etx = (
        df[
            "etx_mean"
        ] < 1
    ).sum()

    if invalid_etx == 0:

        ok(
            "ETX >= 1"
        )

    else:

        msg = (
            f"{invalid_etx} ETX invalide(s)"
        )

        error(msg)
        errors.append(msg)

    # --------------------------------------------------------
    # Radio
    # --------------------------------------------------------

    invalid_radio = (
        (
            df[
                "radio_tx_percent_mean"
            ] < 0
        )
        |
        (
            df[
                "radio_tx_percent_mean"
            ] > 100
        )
    ).sum()

    if invalid_radio == 0:

        ok(
            "Radio TX dans [0,100]"
        )

    else:

        msg = (
            f"{invalid_radio} "
            "Radio TX invalide(s)"
        )

        error(msg)
        errors.append(msg)

    # --------------------------------------------------------
    # Energie
    # --------------------------------------------------------

    invalid_energy = (
        df[
            "energy_estimated_mj_mean"
        ] <= 0
    ).sum()

    if invalid_energy == 0:

        ok(
            "Energie estimée > 0"
        )

    else:

        msg = (
            f"{invalid_energy} valeur(s) "
            "d'énergie invalide(s)"
        )

        error(msg)
        errors.append(msg)


    invalid_energy_tx = (
        df[
            "energy_radio_tx_mj_mean"
        ] < 0
    ).sum()

    if invalid_energy_tx == 0:
        ok(
            "Energie radio TX estimée >= 0"
        )
    else:
        msg = (
            f"{invalid_energy_tx} valeur(s) "
            "d'énergie radio TX invalide(s)"
        )

        error(msg)
        errors.append(msg)

    # --------------------------------------------------------
    # Runs
    # --------------------------------------------------------

    number_runs = (
        df[
            "run_name"
        ]
        .nunique()
    )

    number_configs = len(
        df[
            FEATURE_COLUMNS
        ]
        .drop_duplicates()
    )

    ok(
        f"{number_runs} run(s) détecté(s)"
    )

    ok(
        f"{number_configs} "
        "configuration(s) unique(s)"
    )

    # --------------------------------------------------------
    # Variabilité Features
    # --------------------------------------------------------

    print(
        "\n" + "-" * 70
    )

    print(
        "VARIABILITÉ DES FEATURES"
    )

    print(
        "-" * 70
    )

    for col in FEATURE_COLUMNS:

        values = (
            df[col]
            .dropna()
            .unique()
            .tolist()
        )

        try:

            values = sorted(values)

        except TypeError:

            pass

        print(
            f"{col:22s} "
            f"({len(values)} valeurs) : "
            f"{values}"
        )

        if len(values) < 2:

            msg = (
                f"La feature {col} "
                "ne varie pas."
            )

            warning(msg)
            warnings.append(msg)

    # --------------------------------------------------------
    # Variabilité Targets
    # --------------------------------------------------------

    print(
        "\n" + "-" * 70
    )

    print(
        "VARIABILITÉ DES TARGETS"
    )

    print(
        "-" * 70
    )

    for col in TARGET_COLUMNS:

        n_unique = (
            df[col].nunique()
        )

        std = (
            df[col].std()
        )

        print(
            f"{col:30s} "
            f"uniques={n_unique:<4d} "
            f"std={std:.6f}"
        )

        if n_unique < 2:

            msg = (
                f"La target {col} "
                "est constante."
            )

            warning(msg)
            warnings.append(msg)

    # --------------------------------------------------------
    # Statistiques énergie
    # --------------------------------------------------------

    print(
        "\n" + "-" * 70
    )

    print(
        "ENERGIE ESTIMEE"
    )

    print(
        "-" * 70
    )

    print(
        df[
            "energy_estimated_mj_mean"
        ].describe()
    )

    # --------------------------------------------------------
    # Final
    # --------------------------------------------------------

    print(
        "\n" + "=" * 70
    )

    if errors:

        print(
            "FINAL STATUS: INVALID"
        )

        print(
            "=" * 70
        )

        for index, msg in enumerate(
            errors,
            start=1,
        ):

            print(
                f"{index}. {msg}"
            )

        sys.exit(1)

    print(
        "FINAL STATUS: VALID"
    )

    print(
        "=" * 70
    )

    if warnings:

        print(
            f"\n{len(warnings)} warning(s)"
        )

    print(
        "\nLe dataset est techniquement "
        "valide pour la partie Machine Learning."
    )


if __name__ == "__main__":
    main()