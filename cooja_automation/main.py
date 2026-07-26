import subprocess
import os
import sys
import config
from parse_log import parse_cooja_log


def run_pipeline():
    print("=== DÉBUT DU PIPELINE AUTOMATISÉ COOJA ===")

    # 1. Vérification de l'existence du fichier .csc
    if not os.path.exists(config.CSC_FILE_PATH):
        print(f"[!] Erreur: Le fichier {config.CSC_FILE_PATH} n'existe pas.")
        print("    (as-tu lancé prepare_sim.py avant ?)")
        sys.exit(1)

    # 2. Préparation de la commande Gradle pour Cooja
    env = os.environ.copy()
    env["JAVA_HOME"] = config.JAVA_HOME

    cmd = [
        "./gradlew", "run",
        f"--args=--no-gui {config.CSC_FILE_PATH}"
    ]

    print(f"[*] Lancement de Cooja en mode Headless...")
    print(f"    Dossier de travail : {config.COOJA_DIR}")

    # Arrêt préalable des daemons Gradle pour éviter les conflits Java
    subprocess.run(["./gradlew", "--stop"], cwd=config.COOJA_DIR,
                    env=env, capture_output=True)

    # --- AJOUT : marge de sécurité au-delà du TIMEOUT() défini dans le .csc,
    # pour laisser le temps à la compilation + au démarrage de Cooja.
    # Si ce délai est dépassé, on considère que quelque chose est bloqué
    # (au lieu de rester figé indéfiniment sans le savoir). ---
    safety_margin_sec = 300
    subprocess_timeout = (config.SIMULATION_TIMEOUT_MS / 1000) + safety_margin_sec

    try:
        result = subprocess.run(cmd, cwd=config.COOJA_DIR, env=env,
                                 timeout=subprocess_timeout)
    except subprocess.TimeoutExpired:
        print(f"[!] Erreur: Cooja n'a pas terminé après {subprocess_timeout:.0f}s "
              f"(TIMEOUT attendu : {config.SIMULATION_TIMEOUT_MS/1000:.0f}s).")
        print("    Vérifie que le .csc contient bien un TIMEOUT(...) avec log.testOK(),")
        print("    ou augmente safety_margin_sec si la compilation est juste lente.")
        sys.exit(1)

    # --- AJOUT : vérification explicite du code de retour ---
    if result.returncode != 0:
        print(f"[!] Attention : Cooja a terminé avec un code d'erreur "
              f"({result.returncode}). Vérifie les logs de compilation ci-dessus.")

    # 3. Parsing des logs (même si Cooja a terminé par un Timeout)
    if os.path.exists(config.LOG_FILE_PATH):
        print("\n[*] Extraction et génération du dataset...")
        parse_cooja_log()
        print("=== PIPELINE TERMINÉ AVEC SUCCÈS ===")
    else:
        print("[!] Erreur: Aucun fichier de log généré par Cooja.")
        sys.exit(1)


if __name__ == "__main__":
    run_pipeline()