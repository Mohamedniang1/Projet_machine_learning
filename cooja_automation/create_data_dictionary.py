#!/usr/bin/env python3

from pathlib import Path

import pandas as pd


OUTPUT_FILE = Path(
    "cooja_automation/data_dictionary.csv"
)


DATA_DICTIONARY = [

    {
        "column": "run_name",
        "role": "metadata",
        "family": "experiment",
        "type": "string",
        "unit": "",
        "origin": "experiment_generator.py",
        "used_as_ml_feature": "No",
        "description": (
            "Identifiant unique du run."
        ),
    },

    {
        "column": "seed",
        "role": "metadata",
        "family": "experiment",
        "type": "integer",
        "unit": "",
        "origin": "Cooja",
        "used_as_ml_feature": "No",
        "description": (
            "Graine aléatoire de la simulation."
        ),
    },

    {
        "column": "imin",
        "role": "feature",
        "family": "RPL/Trickle",
        "type": "integer",
        "unit": "exponent",
        "origin": "RPL_CONF_DIO_INTERVAL_MIN",
        "used_as_ml_feature": "Yes",
        "description": (
            "Exposant de l'intervalle Trickle minimal."
        ),
    },

    {
        "column": "imax",
        "role": "feature",
        "family": "RPL/Trickle",
        "type": "integer",
        "unit": "exponent",
        "origin": "RPL Trickle configuration",
        "used_as_ml_feature": "Yes",
        "description": (
            "Exposant représentant l'intervalle "
            "Trickle maximal."
        ),
    },

    {
        "column": "k",
        "role": "feature",
        "family": "RPL/Trickle",
        "type": "integer",
        "unit": "",
        "origin": "RPL_CONF_DIO_REDUNDANCY",
        "used_as_ml_feature": "Yes",
        "description": (
            "Constante de redondance Trickle."
        ),
    },

    {
        "column": "tx_range",
        "role": "feature",
        "family": "radio",
        "type": "float",
        "unit": "m",
        "origin": "Cooja UDGM",
        "used_as_ml_feature": "Yes",
        "description": (
            "Portée de transmission configurée "
            "dans Cooja."
        ),
    },

    {
        "column": "nb_nodes",
        "role": "feature",
        "family": "topology",
        "type": "integer",
        "unit": "nodes",
        "origin": "Cooja topology",
        "used_as_ml_feature": "Yes",
        "description": (
            "Nombre de nœuds simulés."
        ),
    },

    {
        "column": "send_interval",
        "role": "feature",
        "family": "application",
        "type": "integer",
        "unit": "s",
        "origin": "APP_CONF_SEND_INTERVAL",
        "used_as_ml_feature": "Yes",
        "description": (
            "Intervalle nominal entre deux "
            "transmissions applicatives."
        ),
    },

    {
        "column": "objective_function",
        "role": "feature",
        "family": "RPL routing",
        "type": "categorical",
        "unit": "",
        "origin": "RPL_CONF_OF_OCP",
        "used_as_ml_feature": "Yes",
        "description": (
            "Objective Function RPL utilisée. "
            "Valeurs possibles : OF0 ou MRHOF."
        ),
    },

    {
        "column": "n_samples",
        "role": "quality_control",
        "family": "dataset",
        "type": "integer",
        "unit": "samples",
        "origin": "build_run_dataset.py",
        "used_as_ml_feature": "No",
        "description": (
            "Nombre d'observations agrégées "
            "dans le run."
        ),
    },

    {
        "column": "pdr_window_mean",
        "role": "target",
        "family": "QoS",
        "type": "float",
        "unit": "%",
        "origin": "udp-client.c",
        "used_as_ml_feature": "No",
        "description": (
            "Packet Delivery Ratio moyen."
        ),
    },

    {
        "column": "delay_avg_ms_mean",
        "role": "target",
        "family": "QoS",
        "type": "float",
        "unit": "ms",
        "origin": "udp-client.c",
        "used_as_ml_feature": "No",
        "description": (
            "Délai RTT moyen."
        ),
    },

    {
        "column": "rssi_avg_mean",
        "role": "target",
        "family": "radio",
        "type": "float",
        "unit": "dBm",
        "origin": "PACKETBUF_ATTR_RSSI",
        "used_as_ml_feature": "No",
        "description": (
            "RSSI moyen observé."
        ),
    },

    {
        "column": "etx_mean",
        "role": "target",
        "family": "routing",
        "type": "float",
        "unit": "expected transmissions",
        "origin": "Contiki-NG link-stats",
        "used_as_ml_feature": "No",
        "description": (
            "ETX moyen observé."
        ),
    },

    {
        "column": "radio_tx_percent_mean",
        "role": "target",
        "family": "radio_activity",
        "type": "float",
        "unit": "%",
        "origin": "Energest",
        "used_as_ml_feature": "No",
        "description": (
            "Pourcentage moyen de temps passé "
            "en transmission radio."
        ),
    },

    {
        "column": "energy_estimated_mj_mean",
        "role": "target",
        "family": "energy",
        "type": "float",
        "unit": "mJ",
        "origin": (
            "Energest + Tmote Sky reference "
            "electrical model"
        ),
        "used_as_ml_feature": "No",
        "description": (
            "Énergie moyenne estimée par nœud "
            "et par fenêtre de mesure. "
            "Calculée à partir des temps Energest "
            "et d'un profil électrique Tmote Sky "
            "de référence. Ce n'est pas une mesure "
            "physique directe."
        ),
    },
]


def main():

    df = pd.DataFrame(
        DATA_DICTIONARY
    )

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    df.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    print("=" * 70)
    print("DICTIONNAIRE DE DONNEES")
    print("=" * 70)

    print(
        f"\nFichier créé : "
        f"{OUTPUT_FILE}"
    )

    print(
        f"Variables documentées : "
        f"{len(df)}"
    )

    print(
        "\nTargets :"
    )

    for col in df.loc[
        df["role"] == "target",
        "column"
    ]:

        print(
            f"  Y -> {col}"
        )

    print(
        "\n[OK] Documentation terminée."
    )


if __name__ == "__main__":
    main()