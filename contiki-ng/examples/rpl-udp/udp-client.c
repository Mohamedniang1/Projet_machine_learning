/*
 * udp-client.c
 *
 * Collecteur de métriques pour génération de datasets ML.
 *
 * Mesures :
 * - PDR global
 * - PDR par fenêtre corrigé
 * - RTT moyen / min / max
 * - RSSI moyen
 * - ETX du parent préféré
 * - Rang RPL
 * - Rang et ID du parent préféré
 * - Nombre de voisins IPv6
 * - Energest CPU / LPM / TX / LISTEN
 *
 * Correction importante :
 *
 * Chaque paquet transporte maintenant le numéro de la fenêtre
 * dans laquelle il a été émis.
 *
 * Une réponse UDP retardée est donc rattachée à sa fenêtre
 * d'émission et non à la fenêtre pendant laquelle elle arrive.
 *
 * Cela empêche d'obtenir des PDR de fenêtre supérieurs à 100 %.
 */

#include "contiki.h"

#include "net/routing/routing.h"
#include "net/routing/rpl-lite/rpl.h"
#include "net/routing/rpl-lite/rpl-neighbor.h"

#include "net/netstack.h"
#include "net/ipv6/simple-udp.h"
#include "net/ipv6/uip-ds6-nbr.h"

#include "net/packetbuf.h"
#include "net/link-stats.h"
#include "net/linkaddr.h"

#include "sys/energest.h"
#include "sys/log.h"

#include "random.h"

#include <inttypes.h>
#include <stdint.h>
#include <limits.h>


/* ========================================================= */
/* CONFIGURATION GÉNÉRALE                                   */
/* ========================================================= */

#define LOG_MODULE "App"
#define LOG_LEVEL LOG_LEVEL_INFO

#define UDP_CLIENT_PORT 8765
#define UDP_SERVER_PORT 5678


/*
 * Intervalle d'envoi configurable depuis project-conf.h
 *
 * Exemple :
 *
 * #define APP_CONF_SEND_INTERVAL 5
 */

#ifndef APP_CONF_SEND_INTERVAL
#define APP_CONF_SEND_INTERVAL 10
#endif

#define SEND_INTERVAL \
  (APP_CONF_SEND_INTERVAL * CLOCK_SECOND)


/*
 * Une fenêtre statistique toutes les 60 secondes.
 */

#define METRIC_INTERVAL \
  (60 * CLOCK_SECOND)


/*
 * Signature utilisée pour vérifier qu'un écho UDP
 * appartient bien à notre application.
 */

#define PACKET_MAGIC 0x52504C4DUL /* "RPLM" */


/*
 * Valeurs indiquant une métrique non disponible.
 */

#define INVALID_PARENT_ID 65535U
#define INVALID_RANK      65535U
#define INVALID_ETX       0U


/*
 * Identifiant utilisé lorsqu'un slot de fenêtre
 * n'a encore jamais été utilisé.
 */

#define WINDOW_UNUSED_ID UINT32_MAX


/*
 * Nombre de séquences récentes mémorisées.
 *
 * Cela permet de détecter les doublons sans supposer
 * que les réponses arrivent nécessairement dans l'ordre.
 */

#define RX_HISTORY_SIZE 32


/* ========================================================= */
/* PROCESSUS CONTIKI                                        */
/* ========================================================= */

PROCESS(
  udp_client_process,
  "UDP client metric collector"
);

AUTOSTART_PROCESSES(
  &udp_client_process
);


/* ========================================================= */
/* CONNEXION UDP                                            */
/* ========================================================= */

static struct simple_udp_connection udp_conn;


/* ========================================================= */
/* FORMAT DU PAQUET                                         */
/* ========================================================= */

/*
 * window_id permet de savoir dans quelle fenêtre
 * le paquet a été transmis.
 *
 * Le serveur UDP renvoie simplement le paquet tel quel.
 */

struct data_packet {

  uint32_t magic;

  uint32_t seq;

  uint32_t window_id;

  uint16_t source_id;

  clock_time_t tx_time;
};


/* ========================================================= */
/* COMPTEURS GLOBAUX                                        */
/* ========================================================= */

static uint32_t total_tx;

static uint32_t total_rx;

static uint32_t total_duplicates;


/* ========================================================= */
/* HISTORIQUE POUR DÉTECTION DES DOUBLONS                    */
/* ========================================================= */

static uint32_t rx_history[RX_HISTORY_SIZE];

static uint8_t rx_history_count;

static uint8_t rx_history_position;


/* ========================================================= */
/* STRUCTURE D'UNE FENÊTRE                                  */
/* ========================================================= */

struct window_stats {

  /*
   * Identifiant logique de la fenêtre.
   *
   * 0 = première fenêtre
   * 1 = deuxième fenêtre
   * etc.
   */
  uint32_t id;


  /*
   * Temps simulé auquel la fenêtre s'est terminée.
   */
  uint32_t end_time_seconds;


  /* -------------------- TRAFIC -------------------------- */

  uint32_t tx;

  uint32_t rx;

  uint32_t duplicates;


  /* -------------------- DELAY --------------------------- */

  uint32_t delay_sum_ms;

  uint32_t delay_min_ms;

  uint32_t delay_max_ms;


  /* -------------------- RSSI ---------------------------- */

  int32_t rssi_sum;

  uint32_t samples;


  /* -------------------- ENERGEST ------------------------ */

  uint64_t cpu_ticks;

  uint64_t lpm_ticks;

  uint64_t deep_lpm_ticks;

  uint64_t radio_tx_ticks;

  uint64_t radio_listen_ticks;

  uint64_t total_time_ticks;
};


/*
 * Deux fenêtres sont conservées.
 *
 * Exemple :
 *
 * slot 0 = fenêtre précédente
 * slot 1 = fenêtre actuelle
 *
 * Cela laisse une fenêtre entière aux réponses retardées
 * pour arriver avant publication du SUMMARY.
 */

static struct window_stats windows[2];


/*
 * Slot actuellement utilisé pour les nouveaux TX.
 */

static uint8_t current_window_slot;


/*
 * ID de la fenêtre courante.
 */

static uint32_t current_window_id;


/* ========================================================= */
/* RÉFÉRENCES ENERGEST                                      */
/* ========================================================= */

static uint64_t previous_cpu;

static uint64_t previous_lpm;

static uint64_t previous_deep_lpm;

static uint64_t previous_tx;

static uint64_t previous_listen;

static uint64_t previous_total_time;


/* ========================================================= */
/* FONCTIONS UTILITAIRES                                    */
/* ========================================================= */


/*
 * Retourne l'identifiant court du nœud.
 */

static uint16_t
get_node_id(void)
{
  return linkaddr_node_addr.u8[
    LINKADDR_SIZE - 1
  ];
}


/*
 * Compte le nombre de voisins IPv6.
 */

static uint16_t
count_ipv6_neighbors(void)
{
  uint16_t count = 0;

  uip_ds6_nbr_t *nbr;

  for(
    nbr = uip_ds6_nbr_head();
    nbr != NULL;
    nbr = uip_ds6_nbr_next(nbr)
  ) {

    count++;
  }

  return count;
}


/* ========================================================= */
/* INFORMATIONS RPL                                         */
/* ========================================================= */


/*
 * Retourne le rang RPL logique du nœud.
 */

static uint16_t
get_rpl_rank(void)
{
  if(
    !curr_instance.used ||
    curr_instance.dag.rank == RPL_INFINITE_RANK
  ) {

    return INVALID_RANK;
  }

  return DAG_RANK(
    curr_instance.dag.rank
  );
}


/*
 * Retourne le rang du parent préféré.
 */

static uint16_t
get_parent_rank(void)
{
  rpl_nbr_t *parent =
    curr_instance.dag.preferred_parent;

  if(
    parent == NULL ||
    parent->rank == RPL_INFINITE_RANK
  ) {

    return INVALID_RANK;
  }

  return DAG_RANK(
    parent->rank
  );
}


/*
 * Retourne l'identifiant du parent préféré.
 */

static uint16_t
get_parent_id(void)
{
  rpl_nbr_t *parent =
    curr_instance.dag.preferred_parent;

  const linkaddr_t *parent_lladdr;

  if(parent == NULL) {

    return INVALID_PARENT_ID;
  }

  parent_lladdr =
    rpl_neighbor_get_lladdr(parent);

  if(parent_lladdr == NULL) {

    return INVALID_PARENT_ID;
  }

  return parent_lladdr->u8[
    LINKADDR_SIZE - 1
  ];
}


/*
 * Retourne ETX vers le parent préféré * 100.
 *
 * Exemple :
 *
 * 100 = 1.00
 * 125 = 1.25
 * 200 = 2.00
 */

static uint32_t
get_parent_etx_x100(void)
{
  rpl_nbr_t *parent =
    curr_instance.dag.preferred_parent;

  const struct link_stats *stats;

  if(parent == NULL) {

    return INVALID_ETX;
  }

  stats =
    rpl_neighbor_get_link_stats(parent);

  if(
    stats == NULL ||
    !link_stats_is_fresh(stats)
  ) {

    return INVALID_ETX;
  }

#ifdef LINK_STATS_ETX_DIVISOR

  return (
    (uint32_t)stats->etx * 100UL
  ) / LINK_STATS_ETX_DIVISOR;

#else

  return stats->etx;

#endif
}


/* ========================================================= */
/* CALCUL PDR                                               */
/* ========================================================= */


/*
 * Retourne un pourcentage multiplié par 100.
 *
 * Exemple :
 *
 * numerator   = 97
 * denominator = 100
 *
 * résultat = 9700
 *
 * soit 97.00 %
 */

static uint32_t
ratio_x100(
  uint32_t numerator,
  uint32_t denominator
)
{
  if(denominator == 0) {

    return 0;
  }

  return (
    numerator * 10000UL
  ) / denominator;
}


/* ========================================================= */
/* GESTION DES FENÊTRES                                     */
/* ========================================================= */


/*
 * Réinitialise complètement une fenêtre.
 */

static void
reset_window(
  struct window_stats *window,
  uint32_t id
)
{
  window->id = id;

  window->end_time_seconds = 0;


  /* trafic */

  window->tx = 0;

  window->rx = 0;

  window->duplicates = 0;


  /* delay */

  window->delay_sum_ms = 0;

  window->delay_min_ms =
    UINT32_MAX;

  window->delay_max_ms = 0;


  /* RSSI */

  window->rssi_sum = 0;

  window->samples = 0;


  /* Energest */

  window->cpu_ticks = 0;

  window->lpm_ticks = 0;

  window->deep_lpm_ticks = 0;

  window->radio_tx_ticks = 0;

  window->radio_listen_ticks = 0;

  window->total_time_ticks = 0;
}


/*
 * Recherche une fenêtre à partir de son ID.
 */

static struct window_stats *
find_window(
  uint32_t id
)
{
  uint8_t i;

  for(i = 0; i < 2; i++) {

    if(windows[i].id == id) {

      return &windows[i];
    }
  }

  return NULL;
}


/* ========================================================= */
/* DÉTECTION DES DOUBLONS                                   */
/* ========================================================= */


/*
 * Vérifie si un numéro de séquence
 * a déjà été reçu récemment.
 */

static int
sequence_already_received(
  uint32_t seq
)
{
  uint8_t i;

  for(
    i = 0;
    i < rx_history_count;
    i++
  ) {

    if(rx_history[i] == seq) {

      return 1;
    }
  }

  return 0;
}


/*
 * Ajoute une séquence à l'historique.
 */

static void
remember_sequence(
  uint32_t seq
)
{
  rx_history[
    rx_history_position
  ] = seq;

  rx_history_position++;

  if(
    rx_history_position >=
    RX_HISTORY_SIZE
  ) {

    rx_history_position = 0;
  }

  if(
    rx_history_count <
    RX_HISTORY_SIZE
  ) {

    rx_history_count++;
  }
}


/* ========================================================= */
/* ENERGEST                                                 */
/* ========================================================= */


/*
 * Initialise la référence Energest.
 */

static void
initialize_energest_reference(void)
{
  energest_flush();

  previous_cpu =
    energest_type_time(
      ENERGEST_TYPE_CPU
    );

  previous_lpm =
    energest_type_time(
      ENERGEST_TYPE_LPM
    );

  previous_deep_lpm =
    energest_type_time(
      ENERGEST_TYPE_DEEP_LPM
    );

  previous_tx =
    energest_type_time(
      ENERGEST_TYPE_TRANSMIT
    );

  previous_listen =
    energest_type_time(
      ENERGEST_TYPE_LISTEN
    );

  previous_total_time =
    ENERGEST_GET_TOTAL_TIME();
}


/*
 * Capture les deltas Energest correspondant
 * exactement à la fenêtre qui vient de se terminer.
 */

static void
capture_energest_for_window(
  struct window_stats *window
)
{
  uint64_t cpu_now;

  uint64_t lpm_now;

  uint64_t deep_lpm_now;

  uint64_t tx_now;

  uint64_t listen_now;

  uint64_t total_time_now;


  energest_flush();


  cpu_now =
    energest_type_time(
      ENERGEST_TYPE_CPU
    );

  lpm_now =
    energest_type_time(
      ENERGEST_TYPE_LPM
    );

  deep_lpm_now =
    energest_type_time(
      ENERGEST_TYPE_DEEP_LPM
    );

  tx_now =
    energest_type_time(
      ENERGEST_TYPE_TRANSMIT
    );

  listen_now =
    energest_type_time(
      ENERGEST_TYPE_LISTEN
    );

  total_time_now =
    ENERGEST_GET_TOTAL_TIME();


  window->cpu_ticks =
    cpu_now - previous_cpu;

  window->lpm_ticks =
    lpm_now - previous_lpm;

  window->deep_lpm_ticks =
    deep_lpm_now -
    previous_deep_lpm;

  window->radio_tx_ticks =
    tx_now - previous_tx;

  window->radio_listen_ticks =
    listen_now -
    previous_listen;

  window->total_time_ticks =
    total_time_now -
    previous_total_time;


  /*
   * Mise à jour des références pour
   * la fenêtre suivante.
   */

  previous_cpu =
    cpu_now;

  previous_lpm =
    lpm_now;

  previous_deep_lpm =
    deep_lpm_now;

  previous_tx =
    tx_now;

  previous_listen =
    listen_now;

  previous_total_time =
    total_time_now;
}


/* ========================================================= */
/* AFFICHAGE DU SUMMARY                                     */
/* ========================================================= */


static void
print_summary(
  struct window_stats *window
)
{
  uint32_t global_pdr_x100;

  uint32_t window_pdr_x100;

  uint32_t delay_avg_ms;

  uint32_t delay_min_ms;

  uint32_t delay_max_ms;

  int32_t rssi_avg;

  uint64_t energy_ticks;

  uint16_t node_id;

  uint16_t rank;

  uint16_t parent_rank;

  uint16_t parent_id;

  uint16_t neighbor_count;

  uint32_t parent_etx_x100;


  /* ------------------------------------------------------- */
  /* PDR                                                     */
  /* ------------------------------------------------------- */

  global_pdr_x100 =
    ratio_x100(
      total_rx,
      total_tx
    );


  window_pdr_x100 =
    ratio_x100(
      window->rx,
      window->tx
    );


  /* ------------------------------------------------------- */
  /* DELAY / RSSI                                            */
  /* ------------------------------------------------------- */

  if(window->samples > 0) {

    delay_avg_ms =
      window->delay_sum_ms /
      window->samples;

    delay_min_ms =
      window->delay_min_ms;

    delay_max_ms =
      window->delay_max_ms;

    rssi_avg =
      window->rssi_sum /
      (int32_t)window->samples;

  } else {

    delay_avg_ms = 0;

    delay_min_ms = 0;

    delay_max_ms = 0;

    rssi_avg = 0;
  }


  /* ------------------------------------------------------- */
  /* ENERGIE BRUTE                                           */
  /* ------------------------------------------------------- */

  /*
   * Attention :
   *
   * ceci n'est PAS encore une énergie physique en joules.
   *
   * La conversion correcte sera faite ensuite en Python
   * avec les courants CPU / TX / RX et la tension.
   */

  energy_ticks =
    window->cpu_ticks +
    window->lpm_ticks +
    window->deep_lpm_ticks +
    window->radio_tx_ticks +
    window->radio_listen_ticks;


  /* ------------------------------------------------------- */
  /* RPL                                                     */
  /* ------------------------------------------------------- */

  node_id =
    get_node_id();

  rank =
    get_rpl_rank();

  parent_rank =
    get_parent_rank();

  parent_id =
    get_parent_id();

  neighbor_count =
    count_ipv6_neighbors();

  parent_etx_x100 =
    get_parent_etx_x100();


  /* ------------------------------------------------------- */
  /* LOG                                                     */
  /* ------------------------------------------------------- */

  LOG_INFO(
    "SUMMARY,"
    "node=%u,"
    "time=%" PRIu32 ","
    "tx_total=%" PRIu32 ","
    "rx_total=%" PRIu32 ","
    "dup_total=%" PRIu32 ","
    "pdr_global_x100=%" PRIu32 ","
    "tx_window=%" PRIu32 ","
    "rx_window=%" PRIu32 ","
    "dup_window=%" PRIu32 ","
    "pdr_window_x100=%" PRIu32 ","
    "delay_avg_ms=%" PRIu32 ","
    "delay_min_ms=%" PRIu32 ","
    "delay_max_ms=%" PRIu32 ","
    "rssi_avg=%" PRId32 ","
    "etx_x100=%" PRIu32 ","
    "rank=%u,"
    "parent_rank=%u,"
    "parent_id=%u,"
    "neighbors=%u,"
    "cpu_ticks=%" PRIu64 ","
    "lpm_ticks=%" PRIu64 ","
    "deep_lpm_ticks=%" PRIu64 ","
    "radio_tx_ticks=%" PRIu64 ","
    "radio_listen_ticks=%" PRIu64 ","
    "total_time_ticks=%" PRIu64 ","
    "energy_ticks=%" PRIu64 "\n",

    node_id,

    window->end_time_seconds,

    total_tx,

    total_rx,

    total_duplicates,

    global_pdr_x100,

    window->tx,

    window->rx,

    window->duplicates,

    window_pdr_x100,

    delay_avg_ms,

    delay_min_ms,

    delay_max_ms,

    rssi_avg,

    parent_etx_x100,

    rank,

    parent_rank,

    parent_id,

    neighbor_count,

    window->cpu_ticks,

    window->lpm_ticks,

    window->deep_lpm_ticks,

    window->radio_tx_ticks,

    window->radio_listen_ticks,

    window->total_time_ticks,

    energy_ticks
  );
}


/* ========================================================= */
/* RÉCEPTION UDP                                            */
/* ========================================================= */


static void
udp_rx_callback(
  struct simple_udp_connection *c,
  const uip_ipaddr_t *sender_addr,
  uint16_t sender_port,
  const uip_ipaddr_t *receiver_addr,
  uint16_t receiver_port,
  const uint8_t *data,
  uint16_t datalen
)
{
  const struct data_packet *pkt;

  struct window_stats *window;

  clock_time_t now;

  clock_time_t rtt_ticks;

  uint32_t rtt_ms;

  int16_t rssi;


  (void)c;

  (void)sender_addr;

  (void)sender_port;

  (void)receiver_addr;

  (void)receiver_port;


  /* ------------------------------------------------------- */
  /* VALIDATION DU PAQUET                                    */
  /* ------------------------------------------------------- */

  if(
    data == NULL ||
    datalen != sizeof(
      struct data_packet
    )
  ) {

    LOG_WARN(
      "Paquet echo invalide, taille=%u\n",
      datalen
    );

    return;
  }


  pkt =
    (const struct data_packet *)data;


  if(
    pkt->magic !=
    PACKET_MAGIC
  ) {

    LOG_WARN(
      "Paquet avec signature invalide\n"
    );

    return;
  }


  if(
    pkt->source_id !=
    get_node_id()
  ) {

    LOG_WARN(
      "Echo destiné à un autre noeud\n"
    );

    return;
  }


  /*
   * Recherche de la fenêtre à laquelle
   * appartient ce paquet.
   */

  window =
    find_window(
      pkt->window_id
    );


  /* ------------------------------------------------------- */
  /* DOUBLONS                                                */
  /* ------------------------------------------------------- */

  if(
    sequence_already_received(
      pkt->seq
    )
  ) {

    total_duplicates++;

    if(window != NULL) {

      window->duplicates++;
    }

    return;
  }


  remember_sequence(
    pkt->seq
  );


  /* ------------------------------------------------------- */
  /* COMPTEUR GLOBAL                                         */
  /* ------------------------------------------------------- */

  total_rx++;


  /*
   * Le paquet peut être tellement ancien que sa fenêtre
   * a déjà été supprimée.
   *
   * Dans ce cas, il reste compté dans total_rx,
   * mais pas dans une fenêtre.
   *
   * Avec des fenêtres de 60 secondes et des RTT
   * de quelques centaines de ms, ce cas devrait être
   * extrêmement rare.
   */

  if(window != NULL) {

    window->rx++;
  }


  /* ------------------------------------------------------- */
  /* RTT                                                     */
  /* ------------------------------------------------------- */

  now =
    clock_time();

  rtt_ticks =
    now -
    pkt->tx_time;


  rtt_ms =
    (
      (uint32_t)rtt_ticks *
      1000UL
    ) /
    CLOCK_SECOND;


  /* ------------------------------------------------------- */
  /* RSSI                                                    */
  /* ------------------------------------------------------- */

  rssi =
    (int16_t)
    packetbuf_attr(
      PACKETBUF_ATTR_RSSI
    );


  /* ------------------------------------------------------- */
  /* STATISTIQUES DE LA FENÊTRE D'ÉMISSION                  */
  /* ------------------------------------------------------- */

  if(window != NULL) {

    window->delay_sum_ms +=
      rtt_ms;

    window->rssi_sum +=
      rssi;

    window->samples++;


    if(
      rtt_ms <
      window->delay_min_ms
    ) {

      window->delay_min_ms =
        rtt_ms;
    }


    if(
      rtt_ms >
      window->delay_max_ms
    ) {

      window->delay_max_ms =
        rtt_ms;
    }
  }


  /* ------------------------------------------------------- */
  /* LOG PAR PAQUET                                          */
  /* ------------------------------------------------------- */

  LOG_INFO(
    "PACKET,"
    "node=%u,"
    "seq=%" PRIu32 ","
    "window=%" PRIu32 ","
    "rtt_ms=%" PRIu32 ","
    "rssi=%d\n",

    get_node_id(),

    pkt->seq,

    pkt->window_id,

    rtt_ms,

    rssi
  );
}


/* ========================================================= */
/* PROCESSUS PRINCIPAL                                      */
/* ========================================================= */


PROCESS_THREAD(
  udp_client_process,
  ev,
  data
)
{
  static struct etimer send_timer;

  static struct etimer metric_timer;

  static uip_ipaddr_t root_ipaddr;

  static struct data_packet packet;


  PROCESS_BEGIN();


  /* ======================================================= */
  /* INITIALISATION                                          */
  /* ======================================================= */


  total_tx = 0;

  total_rx = 0;

  total_duplicates = 0;


  rx_history_count = 0;

  rx_history_position = 0;


  /*
   * Première fenêtre active.
   */

  current_window_id = 0;

  current_window_slot = 0;


  reset_window(
    &windows[0],
    0
  );


  /*
   * Deuxième slot non utilisé.
   */

  reset_window(
    &windows[1],
    WINDOW_UNUSED_ID
  );


  initialize_energest_reference();


  /* ======================================================= */
  /* BOOT LOG                                                */
  /* ======================================================= */

  LOG_INFO(
    "BOOT,"
    "node=%u,"
    "send_interval_ticks=%lu,"
    "metric_interval_ticks=%lu\n",

    get_node_id(),

    (unsigned long)
    SEND_INTERVAL,

    (unsigned long)
    METRIC_INTERVAL
  );


  /* ======================================================= */
  /* UDP                                                     */
  /* ======================================================= */

  simple_udp_register(
    &udp_conn,

    UDP_CLIENT_PORT,

    NULL,

    UDP_SERVER_PORT,

    udp_rx_callback
  );


  /* ======================================================= */
  /* PREMIER ENVOI                                           */
  /* ======================================================= */

  /*
   * Petit décalage aléatoire afin que tous
   * les nœuds n'émettent pas simultanément.
   */

  etimer_set(
    &send_timer,

    CLOCK_SECOND +
    (
      random_rand() %
      (2 * CLOCK_SECOND)
    )
  );


  /* ======================================================= */
  /* PREMIÈRE FRONTIÈRE DE FENÊTRE                          */
  /* ======================================================= */

  etimer_set(
    &metric_timer,

    METRIC_INTERVAL
  );


  /* ======================================================= */
  /* BOUCLE PRINCIPALE                                       */
  /* ======================================================= */

  while(1) {

    PROCESS_WAIT_EVENT();


    /*
     * IMPORTANT :
     *
     * On traite la frontière de fenêtre AVANT l'envoi.
     *
     * Si send_timer et metric_timer expirent au même moment,
     * le nouveau paquet appartiendra ainsi à la nouvelle
     * fenêtre.
     */

    if(
      etimer_expired(
        &metric_timer
      )
    ) {

      struct window_stats *current_window;

      uint8_t next_slot;


      /*
       * Fenêtre qui vient de se terminer.
       */

      current_window =
        &windows[
          current_window_slot
        ];


      /*
       * Enregistre son temps de fin.
       */

      current_window->
        end_time_seconds =
        (uint32_t)
        clock_seconds();


      /*
       * Capture Energest pour cette fenêtre.
       */

      capture_energest_for_window(
        current_window
      );


      /*
       * Le prochain slot est également celui
       * contenant la fenêtre précédente.
       */

      next_slot =
        (
          current_window_slot +
          1
        ) % 2;


      /*
       * Si ce slot contient une ancienne fenêtre,
       * elle a bénéficié d'une fenêtre complète
       * pour recevoir les réponses retardées.
       *
       * Elle peut donc maintenant être publiée.
       */

      if(
        windows[next_slot].id !=
        WINDOW_UNUSED_ID
      ) {

        print_summary(
          &windows[next_slot]
        );
      }


      /*
       * Création de la nouvelle fenêtre.
       */

      current_window_id++;


      reset_window(
        &windows[next_slot],
        current_window_id
      );


      current_window_slot =
        next_slot;


      /*
       * Relance le timer.
       */

      etimer_reset_with_new_interval(
        &metric_timer,

        METRIC_INTERVAL
      );
    }


    /* ===================================================== */
    /* ENVOI UDP                                              */
    /* ===================================================== */

    if(
      etimer_expired(
        &send_timer
      )
    ) {

      if(
        NETSTACK_ROUTING.
          node_is_reachable()
        &&
        NETSTACK_ROUTING.
          get_root_ipaddr(
            &root_ipaddr
          )
      ) {

        struct window_stats
          *current_window;


        current_window =
          &windows[
            current_window_slot
          ];


        /* compteur global */

        total_tx++;


        /* compteur de la fenêtre */

        current_window->tx++;


        /* préparation du paquet */

        packet.magic =
          PACKET_MAGIC;

        packet.seq =
          total_tx;

        packet.window_id =
          current_window_id;

        packet.source_id =
          get_node_id();

        packet.tx_time =
          clock_time();


        /* envoi */

        simple_udp_sendto(
          &udp_conn,

          &packet,

          sizeof(packet),

          &root_ipaddr
        );
      }


      /*
       * Prochain envoi :
       *
       * SEND_INTERVAL
       * +
       * jitter entre 0 et 2 secondes.
       */

      etimer_reset_with_new_interval(
        &send_timer,

        SEND_INTERVAL +
        (
          random_rand() %
          (
            2 *
            CLOCK_SECOND
          )
        )
      );
    }
  }


  PROCESS_END();
}