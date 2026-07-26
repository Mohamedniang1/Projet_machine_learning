import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Chargement des données
df = pd.read_csv("dataset.csv")

# Style graphique
sns.set_theme(style="whitegrid")
plt.figure(figsize=(14, 10))

# 1. RSSI par Nœud
plt.subplot(2, 2, 1)
sns.boxplot(data=df, x="node_id", y="rssi_dbm", palette="Blues")
plt.title("Distribution du RSSI par Nœud (dBm)")
plt.xlabel("ID du Nœud")
plt.ylabel("RSSI (dBm)")

# 2. Latence par Nœud (hors NaN)
plt.subplot(2, 2, 2)
sns.boxplot(data=df.dropna(subset=["delay_ms"]), x="node_id", y="delay_ms", palette="Greens")
plt.title("Distribution de la Latence (ms)")
plt.xlabel("ID du Nœud")
plt.ylabel("Délai (ms)")

# 3. Évolution temporelle du trafic
plt.subplot(2, 2, 3)
df["sim_min"] = df["timestamp_ms"] / (1000 * 60)
sns.histplot(data=df, x="sim_min", bins=30, kde=True, color="purple")
plt.title("Distribution du Trafic au cours de la Simulation")
plt.xlabel("Temps de Simulation (minutes)")
plt.ylabel("Nombre de Paquets Reçus")

# 4. Relation RSSI vs Latence
plt.subplot(2, 2, 4)
sns.scatterplot(data=df.dropna(subset=["delay_ms"]), x="rssi_dbm", y="delay_ms", hue="node_id", palette="tab10")
plt.title("Relation RSSI vs Latence")
plt.xlabel("RSSI (dBm)")
plt.ylabel("Délai (ms)")

plt.tight_layout()
plt.savefig("simulation_analysis.png", dpi=300)
print("[+] Graphiques enregistrés sous : simulation_analysis.png")
plt.show()