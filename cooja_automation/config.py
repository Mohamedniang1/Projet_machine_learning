import os

# Chemins absolus dynamiques basés sur l'emplacement de config.py
AUTOMATION_DIR = os.path.dirname(os.path.abspath(__file__)) # PROJETSTAGE/cooja_automation
PROJECT_ROOT = os.path.dirname(AUTOMATION_DIR)             # PROJETSTAGE

# Chemins Contiki-NG
COOJA_DIR = os.path.join(PROJECT_ROOT, "contiki-ng", "tools", "cooja")
RPL_UDP_DIR = os.path.join(PROJECT_ROOT, "contiki-ng", "examples", "rpl-udp")

# Fichiers de simulation et logs
CSC_FILE_PATH = os.path.join(RPL_UDP_DIR, "simulation_rpl.csc")
LOG_FILE_PATH = os.path.join(COOJA_DIR, "COOJA.testlog")
DATASET_CSV_PATH = os.path.join(AUTOMATION_DIR, "dataset.csv")

# Configuration de l'environnement
JAVA_HOME = "/usr/lib/jvm/java-17-openjdk-amd64"
SIMULATION_TIMEOUT_MS = 3600000  # 1 heure