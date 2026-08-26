#!/usr/bin/env python3

from pathlib import Path

import pandas as pd


# ============================================================
# FICHIERS
# ============================================================

INPUT_FILE = Path(
    "cooja_automation/dataset_runs.csv"
)

OUTPUT_FILE = Path(
    "cooja_automation/dataset_ml_ready.csv"
)


# ============================================================
# METADONNEES
# ============================================================

IDENTIFICATION_COLUMNS = [
    "run_name",
    "seed",
]


# ============================================================
# FEATURES
# ============================================================

NUMERIC_FEATURE_COLUMNS = [
    "imin",
    "imax",
    "k",
    "tx_range",
    "nb_nodes",
    "send_interval",
]

CATEGORICAL_FEATURE_COLUMNS = [
    "objective_function",
]

FEATURE_COLUMNS = (
    NUMERIC_FEATURE_COLUMNS
    + CATEGORICAL_FEATURE_COLUMNS
)


# ============================================================
# CONTROLE QUALITE
# ============================================================

QUALITY_COLUMNS = [
    "n_samples",
]


# ============================================================
# TARGETS
# ============================================================

TARGET_COLUMNS = [
    "pdr_window_mean",
    "delay_avg_ms_mean",
    "rssi_avg_mean",
    "etx_mean",
    "radio_tx_percent_mean",
    "energy_estimated_mj_mean",
    "energy_radio_tx_mj_mean",
]


SELECTED_COLUMNS = (
    IDENTIFICATION_COLUMNS
    + FEATURE_COLUMNS
    + QUALITY_COLUMNS
    + TARGET_COLUMNS
)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("PREPARATION DU DATASET MACHINE LEARNING")
    print("=" * 70)

    if not INPUT_FILE.exists():

        raise FileNotFoundError(
            f"Fichier introuvable : "
            f"{INPUT_FILE}"
        )

    df = pd.read_csv(
        INPUT_FILE
    )

    print(
        f"\nDataset source : "
        f"{INPUT_FILE}"
    )

    print(
        f"Lignes source  : "
        f"{len(df)}"
    )

    print(
        f"Colonnes source: "
        f"{len(df.columns)}"
    )

    # --------------------------------------------------------
    # Colonnes nécessaires
    # --------------------------------------------------------

    missing_columns = [
        col
        for col in SELECTED_COLUMNS
        if col not in df.columns
    ]

    if missing_columns:

        raise ValueError(
            "Colonnes manquantes : "
            + ", ".join(
                missing_columns
            )
        )

    print(
        "[OK] Toutes les colonnes nécessaires "
        "sont présentes."
    )

    # --------------------------------------------------------
    # Sélection
    # --------------------------------------------------------

    ml_df = df[
        SELECTED_COLUMNS
    ].copy()

    # --------------------------------------------------------
    # Numérique
    # --------------------------------------------------------

    numeric_columns = (
        NUMERIC_FEATURE_COLUMNS
        + QUALITY_COLUMNS
        + TARGET_COLUMNS
    )

    for col in numeric_columns:

        ml_df[col] = pd.to_numeric(
            ml_df[col],
            errors="coerce",
        )

    # --------------------------------------------------------
    # Objective Function
    # --------------------------------------------------------

    ml_df[
        "objective_function"
    ] = (
        ml_df[
            "objective_function"
        ]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    allowed_of = {
        "OF0",
        "MRHOF",
    }

    invalid_of = (
        ~ml_df[
            "objective_function"
        ].isin(
            allowed_of
        )
    )

    if invalid_of.any():

        raise ValueError(
            "Objective Function invalide."
        )

    print(
        "[OK] Objective Functions valides : "
        "MRHOF / OF0"
    )

    # --------------------------------------------------------
    # Missing
    # --------------------------------------------------------

    missing = (
        ml_df
        .isna()
        .sum()
    )

    if missing.sum() == 0:

        print(
            "[OK] Aucune valeur manquante."
        )

    else:

        print(
            missing[
                missing > 0
            ]
        )

        raise ValueError(
            "Valeurs manquantes détectées."
        )

    # --------------------------------------------------------
    # Vérifications physiques
    # --------------------------------------------------------

    invalid_pdr = (
        (
            ml_df[
                "pdr_window_mean"
            ] < 0
        )
        |
        (
            ml_df[
                "pdr_window_mean"
            ] > 100
        )
    ).sum()

    invalid_delay = (
        ml_df[
            "delay_avg_ms_mean"
        ] < 0
    ).sum()

    invalid_etx = (
        ml_df[
            "etx_mean"
        ] < 1
    ).sum()

    invalid_radio = (
        (
            ml_df[
                "radio_tx_percent_mean"
            ] < 0
        )
        |
        (
            ml_df[
                "radio_tx_percent_mean"
            ] > 100
        )
    ).sum()

    invalid_energy = (
        ml_df[
            "energy_estimated_mj_mean"
        ] <= 0
    ).sum()

    print(
        f"\nPDR invalides    : {invalid_pdr}"
    )

    print(
        f"Delay invalides  : {invalid_delay}"
    )

    print(
        f"ETX invalides    : {invalid_etx}"
    )

    print(
        f"Radio invalides  : {invalid_radio}"
    )

    print(
        f"Energy invalides : {invalid_energy}"
    )

    if (
        invalid_pdr
        or invalid_delay
        or invalid_etx
        or invalid_radio
        or invalid_energy
    ):

        raise ValueError(
            "Valeurs invalides détectées."
        )

    # --------------------------------------------------------
    # Configurations
    # --------------------------------------------------------

    configurations = (
        ml_df[
            FEATURE_COLUMNS
        ]
        .drop_duplicates()
    )

    print(
        f"\nNombre de configurations uniques : "
        f"{len(configurations)}"
    )

    print(
        f"Nombre de runs : "
        f"{len(ml_df)}"
    )

    # --------------------------------------------------------
    # Features
    # --------------------------------------------------------

    print(
        "\nValeurs expérimentales disponibles :"
    )

    for col in FEATURE_COLUMNS:

        values = (
            ml_df[col]
            .dropna()
            .unique()
            .tolist()
        )

        try:

            values = sorted(
                values
            )

        except TypeError:

            pass

        print(
            f"  {col:22s} : "
            f"{values}"
        )

    # --------------------------------------------------------
    # Targets
    # --------------------------------------------------------

    print(
        "\nStatistiques des targets :\n"
    )

    print(
        ml_df[
            TARGET_COLUMNS
        ].describe()
    )

    # --------------------------------------------------------
    # Sauvegarde
    # --------------------------------------------------------

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    ml_df.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    print(
        "\n" + "=" * 70
    )

    print(
        "DATASET ML READY"
    )

    print(
        "=" * 70
    )

    print(
        f"\nFichier créé : "
        f"{OUTPUT_FILE}"
    )

    print(
        f"Dimensions : "
        f"{ml_df.shape}"
    )

    print(
        "\nFeatures :"
    )

    for col in FEATURE_COLUMNS:

        print(
            f"  X -> {col}"
        )

    print(
        "\nTargets :"
    )

    for col in TARGET_COLUMNS:

        print(
            f"  Y -> {col}"
        )

    print(
        "\n[OK] Préparation terminée."
    )


if __name__ == "__main__":
    main()