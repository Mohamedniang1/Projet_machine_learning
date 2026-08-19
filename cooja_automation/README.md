   ### Objectif du projet ###
   Le travail actuel consiste à développer un module d'apprentissage automatique indépendant capable d'identifier les paramètres réseau RPL ayant le plus d'impact sur un objectif donné (par exemple : économie d'énergie, qualité de service, délai ou fiabilité).
   
    ### LE ROLE DE CHAQUE FICHIER ###   

udp-client.c : chaque mote (sauf la racine) envoie périodiquement un paquet UDP vers le serveur.

Udp-server : reçoit les paquets de tous les clients, calcule les métriques, les imprime dans le log.

experiment_generator.py : Il permet de generer plusieurs type de config mais en réalité il ne fait aucune simulation, il dit seulement :
        - fais une simulation avec : Seed = 15, Imin = 8 et Imax = 16
    
        - Puis avec : Seed = 24, Imin = 10 et Imax = 18 etc...


simulation.csc : Ce fichier contient : nombre de nœuds firmware, position, radio, plugins, durée, seed

run_cooja.py : il recoit Seed = 15, Imin = 8 et Imax = 16 ensuite il modifie le fichier modifier simulation.csc, lance cooja et attendre, a la fin il retourne le chemin du log (log/test unique)

parse_log.py : transforme le log de Cooja (un fichier texte avec des milliers de lignes, dont la plupart ne nous intéressent pas) en un fichier CSV propre et exploitable (dataset.csv) contenant uniquement les métriques réseau utiles pour le modèle de classification.

### Le role des parametres #############
Le paramètre k définit combien de messages DIO similaires un nœud peut entendre avant de décider :
La fonction objectif influence la manière dont RPL choisit les chemins/parents.
