udp-client.c : chaque mote (sauf la racine) envoie périodiquement un paquet UDP vers le serveur.

Udp-server : reçoit les paquets de tous les clients, calcule les métriques, les imprime dans le log.

parse_log.py : transforme le log brut de Cooja (un fichier texte avec des milliers de lignes, dont la plupart ne nous intéressent pas) en un fichier CSV propre et exploitable (dataset.csv) contenant uniquement les métriques réseau utiles pour ton modèle de classification.

