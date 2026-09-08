/*
 * udp-client.c
 *
 * Campagne expérimentale RPL / Sky / CC2420
 *
 * Réseau :
 * - 36 noeuds au total
 * - 1 root
 * - 35 clients
 * - RPL-Lite
 * - CSMA
 *
 * Trafic :
 * - phase de convergence : 600 s
 * - phase de mesure : 36 fenêtres
 * - durée d'une fenêtre : 600 s
 * - exactement 1 tentative applicative par client / fenêtre
 * - instant aléatoire dans [0, 599] s
 * - payload applicatif : exactement 10 octets
 *
 * IMPORTANT :
 *
 * Une ligne TX représente une tentative applicative.
 *
 * Même si aucune route n'est disponible au moment choisi,
 * le message est compté comme généré pour cette fenêtre.
 *
 * Cela garantit :
 *
 * 35 clients × 36 fenêtres = 1260 TX applicatifs.
 *
 * Le champ udp_sent indique si simple_udp_sendto()
 * a réellement pu être appelé avec une adresse root connue.
 */

#include "contiki.h"

#include "net/routing/routing.h"
#include "net/routing/rpl-lite/rpl.h"
#include "net/routing/rpl-lite/rpl-neighbor.h"

#include "net/netstack.h"

#include "net/ipv6/simple-udp.h"
#include "net/ipv6/uip-ds6-nbr.h"

#include "net/link-stats.h"
#include "net/linkaddr.h"

#include "dev/radio.h"

#include "sys/energest.h"
#include "sys/log.h"

#include "random.h"

#include <inttypes.h>
#include <stdint.h>


/* ========================================================= */
/* LOG                                                       */
/* ========================================================= */

#define LOG_MODULE "App"
#define LOG_LEVEL LOG_LEVEL_INFO


/* ========================================================= */
/* UDP                                                       */
/* ========================================================= */

#define UDP_CLIENT_PORT 8765
#define UDP_SERVER_PORT 5678


/* ========================================================= */
/* TRAFIC                                                    */
/* ========================================================= */

/*
 * Une fenêtre = 10 minutes.
 */
#ifndef APP_CONF_TRAFFIC_WINDOW_SECONDS
#define APP_CONF_TRAFFIC_WINDOW_SECONDS 600
#endif


/*
 * Phase initiale sans trafic applicatif.
 */
#ifndef APP_CONF_TRAFFIC_START_SECONDS
#define APP_CONF_TRAFFIC_START_SECONDS 600
#endif


/*
 * 6 heures de mesure :
 *
 * 6 h = 21600 s
 * 21600 / 600 = 36 fenêtres
 */
#ifndef APP_CONF_MEASUREMENT_WINDOWS
#define APP_CONF_MEASUREMENT_WINDOWS 36
#endif


/* ========================================================= */
/* PAYLOAD                                                   */
/* ========================================================= */

#ifndef APP_CONF_PAYLOAD_SIZE
#define APP_CONF_PAYLOAD_SIZE 10
#endif


#if APP_CONF_PAYLOAD_SIZE != 10
#error "APP_CONF_PAYLOAD_SIZE doit etre egal a 10"
#endif


/*
 * Format exact :
 *
 * [0]    magic R
 * [1]    magic P
 *
 * [2-3]  source_id
 * [4-5]  sequence
 * [6-9]  window_id
 *
 * Total = 10 octets.
 */

#define PAYLOAD_MAGIC_0 0x52
#define PAYLOAD_MAGIC_1 0x50


/* ========================================================= */
/* PUISSANCE RADIO                                           */
/* ========================================================= */

#ifndef APP_CONF_TX_POWER_DBM
#define APP_CONF_TX_POWER_DBM 0
#endif


/* ========================================================= */
/* TIMERS                                                    */
/* ========================================================= */

#define TRAFFIC_WINDOW_TICKS \
  ((clock_time_t)APP_CONF_TRAFFIC_WINDOW_SECONDS * CLOCK_SECOND)

#define TRAFFIC_START_TICKS \
  ((clock_time_t)APP_CONF_TRAFFIC_START_SECONDS * CLOCK_SECOND)


/* ========================================================= */
/* VALEURS INVALIDES                                         */
/* ========================================================= */

#define INVALID_PARENT_ID 65535U
#define INVALID_RANK      65535U
#define INVALID_ETX       0U
#define INVALID_RSSI      32767


/* ========================================================= */
/* PROCESSUS                                                 */
/* ========================================================= */

PROCESS(
  udp_client_process,
  "RPL UDP client"
);

AUTOSTART_PROCESSES(
  &udp_client_process
);


/* ========================================================= */
/* UDP                                                       */
/* ========================================================= */

static struct simple_udp_connection udp_conn;


/* ========================================================= */
/* ETAT DE L'EXPERIENCE                                      */
/* ========================================================= */

/*
 * ID de fenêtre :
 *
 * 0 ... 35
 */
static uint32_t current_window_id;


/*
 * Nombre de fenêtres complètement terminées.
 */
static uint16_t completed_windows;


/*
 * Numéro de séquence applicatif.
 */
static uint16_t sequence_number;


/*
 * Nombre total de messages applicatifs générés.
 *
 * A la fin :
 * total_tx = 36
 * pour chaque client.
 */
static uint32_t total_tx;


/*
 * Nombre de fois où simple_udp_sendto()
 * a réellement été appelé.
 */
static uint32_t total_udp_sent;


/*
 * Offset aléatoire de l'envoi dans la fenêtre.
 */
static uint16_t scheduled_offset_s;


/*
 * Garantit une seule tentative dans la fenêtre.
 */
static uint8_t sent_this_window;


/*
 * Indique si simple_udp_sendto() a été appelé
 * pendant la fenêtre.
 */
static uint8_t udp_sent_this_window;


/* ========================================================= */
/* ROOT IP                                                   */
/* ========================================================= */

/*
 * On garde en mémoire la dernière adresse du root connue.
 *
 * Cela permet de tenter l'envoi même si
 * node_is_reachable() devient temporairement faux.
 */
static uip_ipaddr_t cached_root_ipaddr;

static uint8_t root_ip_known;


/* ========================================================= */
/* ENERGEST                                                  */
/* ========================================================= */

static uint64_t previous_cpu;
static uint64_t previous_lpm;
static uint64_t previous_deep_lpm;
static uint64_t previous_tx;
static uint64_t previous_listen;
static uint64_t previous_total_time;


/* ========================================================= */
/* NODE ID                                                   */
/* ========================================================= */

static uint16_t
get_node_id(void)
{
  return linkaddr_node_addr.u8[
    LINKADDR_SIZE - 1
  ];
}


/* ========================================================= */
/* TX POWER                                                  */
/* ========================================================= */

static void
configure_tx_power(void)
{
  radio_value_t actual_power;


  if(
    NETSTACK_RADIO.set_value(
      RADIO_PARAM_TXPOWER,
      (radio_value_t)APP_CONF_TX_POWER_DBM
    )
    ==
    RADIO_RESULT_OK
  ) {

    if(
      NETSTACK_RADIO.get_value(
        RADIO_PARAM_TXPOWER,
        &actual_power
      )
      ==
      RADIO_RESULT_OK
    ) {

      LOG_INFO(
        "TXPWR,%d,%d\n",
        APP_CONF_TX_POWER_DBM,
        (int)actual_power
      );
    }
  }
}


/* ========================================================= */
/* PAYLOAD 10 OCTETS                                         */
/* ========================================================= */

static void
build_payload(
  uint8_t *payload,
  uint16_t source_id,
  uint16_t seq,
  uint32_t window_id
)
{
  /*
   * Magic RP
   */
  payload[0] = PAYLOAD_MAGIC_0;
  payload[1] = PAYLOAD_MAGIC_1;


  /*
   * Source ID
   */
  payload[2] =
    (uint8_t)(
      source_id >> 8
    );

  payload[3] =
    (uint8_t)(
      source_id & 0xff
    );


  /*
   * Sequence
   */
  payload[4] =
    (uint8_t)(
      seq >> 8
    );

  payload[5] =
    (uint8_t)(
      seq & 0xff
    );


  /*
   * Window ID
   */
  payload[6] =
    (uint8_t)(
      window_id >> 24
    );

  payload[7] =
    (uint8_t)(
      window_id >> 16
    );

  payload[8] =
    (uint8_t)(
      window_id >> 8
    );

  payload[9] =
    (uint8_t)(
      window_id & 0xff
    );
}


/* ========================================================= */
/* VOISINS                                                   */
/* ========================================================= */

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
/* RPL RANK                                                  */
/* ========================================================= */

static uint16_t
get_rpl_rank(void)
{
  if(
    !curr_instance.used
    ||
    curr_instance.dag.rank ==
      RPL_INFINITE_RANK
  ) {

    return INVALID_RANK;
  }


  return DAG_RANK(
    curr_instance.dag.rank
  );
}


/* ========================================================= */
/* PARENT                                                    */
/* ========================================================= */

static rpl_nbr_t *
get_preferred_parent(void)
{
  if(
    !curr_instance.used
  ) {

    return NULL;
  }


  return
    curr_instance.dag.preferred_parent;
}


/* ========================================================= */
/* PARENT RANK                                               */
/* ========================================================= */

static uint16_t
get_parent_rank(void)
{
  rpl_nbr_t *parent =
    get_preferred_parent();


  if(
    parent == NULL
    ||
    parent->rank ==
      RPL_INFINITE_RANK
  ) {

    return INVALID_RANK;
  }


  return DAG_RANK(
    parent->rank
  );
}


/* ========================================================= */
/* PARENT ID                                                 */
/* ========================================================= */

static uint16_t
get_parent_id(void)
{
  rpl_nbr_t *parent =
    get_preferred_parent();

  const linkaddr_t *lladdr;


  if(
    parent == NULL
  ) {

    return INVALID_PARENT_ID;
  }


  lladdr =
    rpl_neighbor_get_lladdr(
      parent
    );


  if(
    lladdr == NULL
  ) {

    return INVALID_PARENT_ID;
  }


  return lladdr->u8[
    LINKADDR_SIZE - 1
  ];
}


/* ========================================================= */
/* LINK STATS DU PARENT                                      */
/* ========================================================= */

static const struct link_stats *
get_parent_link_stats(void)
{
  rpl_nbr_t *parent =
    get_preferred_parent();


  if(
    parent == NULL
  ) {

    return NULL;
  }


  return
    rpl_neighbor_get_link_stats(
      parent
    );
}


/* ========================================================= */
/* ETX x100                                                  */
/* ========================================================= */

static uint32_t
get_parent_etx_x100(void)
{
  const struct link_stats *stats =
    get_parent_link_stats();


  if(
    stats == NULL
    ||
    !link_stats_is_fresh(
      stats
    )
  ) {

    return INVALID_ETX;
  }


#ifdef LINK_STATS_ETX_DIVISOR

  return (
    (uint32_t)stats->etx *
    100UL
  )
  /
  LINK_STATS_ETX_DIVISOR;

#else

  return stats->etx;

#endif
}


/* ========================================================= */
/* RSSI DU PARENT                                            */
/* ========================================================= */

static int16_t
get_parent_rssi(void)
{
  const struct link_stats *stats =
    get_parent_link_stats();


  if(
    stats == NULL
  ) {

    return INVALID_RSSI;
  }


#ifdef LINK_STATS_RSSI_UNKNOWN

  if(
    stats->rssi ==
    LINK_STATS_RSSI_UNKNOWN
  ) {

    return INVALID_RSSI;
  }

#endif


  return stats->rssi;
}


/* ========================================================= */
/* ROOT IP                                                   */
/* ========================================================= */

static void
refresh_root_ip(void)
{
  uip_ipaddr_t root_ip;


  /*
   * Si Contiki connaît actuellement le root,
   * on met à jour le cache.
   */
  if(
    NETSTACK_ROUTING.get_root_ipaddr(
      &root_ip
    )
  ) {

    uip_ipaddr_copy(
      &cached_root_ipaddr,
      &root_ip
    );

    root_ip_known = 1;
  }
}


/* ========================================================= */
/* ENERGEST INIT                                             */
/* ========================================================= */

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


/* ========================================================= */
/* SUMMARY DE FENETRE                                        */
/* ========================================================= */

static void
print_window_summary(void)
{
  uint64_t cpu_now;
  uint64_t lpm_now;
  uint64_t deep_lpm_now;
  uint64_t tx_now;
  uint64_t listen_now;
  uint64_t total_time_now;

  uint64_t cpu_delta;
  uint64_t lpm_delta;
  uint64_t deep_lpm_delta;
  uint64_t tx_delta;
  uint64_t listen_delta;
  uint64_t total_time_delta;

  uint16_t rank;
  uint16_t parent_rank;
  uint16_t parent_id;
  uint16_t neighbors;

  uint32_t etx_x100;

  int16_t parent_rssi;

  uint8_t connected;


  /* ------------------------------------------------------- */
  /* Energest                                                */
  /* ------------------------------------------------------- */

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


  cpu_delta =
    cpu_now -
    previous_cpu;


  lpm_delta =
    lpm_now -
    previous_lpm;


  deep_lpm_delta =
    deep_lpm_now -
    previous_deep_lpm;


  tx_delta =
    tx_now -
    previous_tx;


  listen_delta =
    listen_now -
    previous_listen;


  total_time_delta =
    total_time_now -
    previous_total_time;


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


  /* ------------------------------------------------------- */
  /* RPL                                                     */
  /* ------------------------------------------------------- */

  connected =
    NETSTACK_ROUTING.node_is_reachable()
    ?
    1
    :
    0;


  rank =
    get_rpl_rank();


  parent_rank =
    get_parent_rank();


  parent_id =
    get_parent_id();


  neighbors =
    count_ipv6_neighbors();


  etx_x100 =
    get_parent_etx_x100();


  parent_rssi =
    get_parent_rssi();


  /* ------------------------------------------------------- */
  /* Log                                                     */
  /* ------------------------------------------------------- */

  LOG_INFO(
    "SUMMARY,"
    "node=%u,"
    "time=%lu,"
    "window=%lu,"
    "scheduled_s=%u,"
    "tx_total=%lu,"
    "tx_window=%u,"
    "udp_sent_total=%lu,"
    "udp_sent_window=%u,"
    "connected=%u,"
    "rank=%u,"
    "parent_rank=%u,"
    "parent_id=%u,"
    "neighbors=%u,"
    "etx_x100=%lu,"
    "rssi_parent=%d,"
    "cpu_ticks=%" PRIu64 ","
    "lpm_ticks=%" PRIu64 ","
    "deep_lpm_ticks=%" PRIu64 ","
    "radio_tx_ticks=%" PRIu64 ","
    "radio_listen_ticks=%" PRIu64 ","
    "total_time_ticks=%" PRIu64 "\n",

    get_node_id(),

    (unsigned long)
    clock_seconds(),

    (unsigned long)
    current_window_id,

    scheduled_offset_s,

    (unsigned long)
    total_tx,

    sent_this_window,

    (unsigned long)
    total_udp_sent,

    udp_sent_this_window,

    connected,

    rank,

    parent_rank,

    parent_id,

    neighbors,

    (unsigned long)
    etx_x100,

    parent_rssi,

    cpu_delta,

    lpm_delta,

    deep_lpm_delta,

    tx_delta,

    listen_delta,

    total_time_delta
  );
}


/* ========================================================= */
/* PLANIFICATION D'UNE FENETRE                               */
/* ========================================================= */

static clock_time_t
choose_send_delay(void)
{
  scheduled_offset_s =
    (uint16_t)(
      random_rand()
      %
      APP_CONF_TRAFFIC_WINDOW_SECONDS
    );


  /*
   * Evite un etimer de durée 0.
   *
   * L'offset logique reste bien 0 seconde.
   */
  if(
    scheduled_offset_s == 0
  ) {

    return 1;
  }


  return (
    (clock_time_t)scheduled_offset_s
    *
    CLOCK_SECOND
  );
}


/* ========================================================= */
/* PROCESSUS PRINCIPAL                                       */
/* ========================================================= */

PROCESS_THREAD(
  udp_client_process,
  ev,
  data
)
{
  static struct etimer warmup_timer;

  static struct etimer window_timer;

  static struct etimer send_timer;


  static uint8_t payload[
    APP_CONF_PAYLOAD_SIZE
  ];


  static clock_time_t send_delay_ticks;


  static uint8_t reachable;


  PROCESS_BEGIN();


  /* ======================================================= */
  /* INITIALISATION                                          */
  /* ======================================================= */

  current_window_id = 0;

  completed_windows = 0;

  sequence_number = 0;

  total_tx = 0;

  total_udp_sent = 0;

  sent_this_window = 0;

  udp_sent_this_window = 0;

  root_ip_known = 0;


  /* ======================================================= */
  /* RADIO                                                   */
  /* ======================================================= */

  configure_tx_power();


  /* ======================================================= */
  /* UDP                                                     */
  /* ======================================================= */

  /*
   * Pas de callback.
   *
   * Le root ne fait plus d'echo.
   */
  simple_udp_register(
    &udp_conn,
    UDP_CLIENT_PORT,
    NULL,
    UDP_SERVER_PORT,
    NULL
  );


  LOG_INFO(
    "BOOT,%u\n",
    get_node_id()
  );


  /* ======================================================= */
  /* CONVERGENCE                                             */
  /* ======================================================= */

  etimer_set(
    &warmup_timer,
    TRAFFIC_START_TICKS
  );


  PROCESS_WAIT_EVENT_UNTIL(
    etimer_expired(
      &warmup_timer
    )
  );


  /*
   * On récupère immédiatement l'adresse
   * du root si elle est connue.
   */
  refresh_root_ip();


  /*
   * Début des mesures énergétiques.
   */
  initialize_energest_reference();


  LOG_INFO(
    "TRAFFIC_START,%u\n",
    get_node_id()
  );


  /* ======================================================= */
  /* FENETRE 0                                               */
  /* ======================================================= */

  current_window_id = 0;

  sent_this_window = 0;

  udp_sent_this_window = 0;


  send_delay_ticks =
    choose_send_delay();


  etimer_set(
    &send_timer,
    send_delay_ticks
  );


  etimer_set(
    &window_timer,
    TRAFFIC_WINDOW_TICKS
  );


  /* ======================================================= */
  /* BOUCLE                                                  */
  /* ======================================================= */

  while(1) {

    PROCESS_WAIT_EVENT();


    /* ===================================================== */
    /* ENVOI APPLICATIF                                      */
    /* ===================================================== */

    if(
      !sent_this_window
      &&
      etimer_expired(
        &send_timer
      )
    ) {

      /*
       * Très important :
       *
       * à partir d'ici, cette fenêtre est considérée
       * comme ayant produit son UNIQUE message.
       *
       * Aucun retry.
       */
      sent_this_window = 1;


      /*
       * Nouveau numéro de séquence.
       */
      sequence_number++;


      /*
       * Compteur applicatif.
       *
       * Il augmente UNE fois par fenêtre,
       * qu'une route existe ou non.
       */
      total_tx++;


      /* --------------------------------------------------- */
      /* Payload 10 octets                                   */
      /* --------------------------------------------------- */

      build_payload(
        payload,
        get_node_id(),
        sequence_number,
        current_window_id
      );


      /* --------------------------------------------------- */
      /* Etat RPL                                            */
      /* --------------------------------------------------- */

      reachable =
        NETSTACK_ROUTING.node_is_reachable()
        ?
        1
        :
        0;


      /*
       * Actualise l'adresse root lorsqu'elle
       * est actuellement disponible.
       */
      refresh_root_ip();


      /* --------------------------------------------------- */
      /* Tentative UDP                                       */
      /* --------------------------------------------------- */

      udp_sent_this_window = 0;


      /*
       * Si le root a déjà été découvert,
       * on appelle simple_udp_sendto()
       * même si reachable vaut actuellement 0.
       *
       * Le paquet pourra ensuite être perdu
       * dans la couche réseau, ce qui fait partie
       * de la performance que l'on veut mesurer.
       */
      if(
        root_ip_known
      ) {

        simple_udp_sendto(
          &udp_conn,
          payload,
          APP_CONF_PAYLOAD_SIZE,
          &cached_root_ipaddr
        );


        total_udp_sent++;

        udp_sent_this_window = 1;
      }


      /* --------------------------------------------------- */
      /* Log TX                                              */
      /* --------------------------------------------------- */

      LOG_INFO(
        "TX,"
        "node=%u,"
        "seq=%u,"
        "window=%lu,"
        "reachable=%u,"
        "root_known=%u,"
        "udp_sent=%u\n",

        get_node_id(),

        sequence_number,

        (unsigned long)
        current_window_id,

        reachable,

        root_ip_known,

        udp_sent_this_window
      );
    }


    /* ===================================================== */
    /* FIN DE FENETRE                                        */
    /* ===================================================== */

    if(
      etimer_expired(
        &window_timer
      )
    ) {

      /*
       * Même dans le cas extrêmement improbable
       * où le send timer n'aurait pas été exécuté,
       * on force ici une trace de tentative.
       *
       * En pratique offset <= 599 s,
       * donc elle doit toujours être passée avant 600 s.
       */
      if(
        !sent_this_window
      ) {

        sent_this_window = 1;

        sequence_number++;

        total_tx++;


        build_payload(
          payload,
          get_node_id(),
          sequence_number,
          current_window_id
        );


        reachable =
          NETSTACK_ROUTING.node_is_reachable()
          ?
          1
          :
          0;


        refresh_root_ip();


        udp_sent_this_window = 0;


        if(
          root_ip_known
        ) {

          simple_udp_sendto(
            &udp_conn,
            payload,
            APP_CONF_PAYLOAD_SIZE,
            &cached_root_ipaddr
          );


          total_udp_sent++;

          udp_sent_this_window = 1;
        }


        LOG_INFO(
          "TX,"
          "node=%u,"
          "seq=%u,"
          "window=%lu,"
          "reachable=%u,"
          "root_known=%u,"
          "udp_sent=%u\n",

          get_node_id(),

          sequence_number,

          (unsigned long)
          current_window_id,

          reachable,

          root_ip_known,

          udp_sent_this_window
        );
      }


      /* --------------------------------------------------- */
      /* Summary                                             */
      /* --------------------------------------------------- */

      print_window_summary();


      completed_windows++;


      /* =================================================== */
      /* FIN DES 36 FENETRES                                 */
      /* =================================================== */

      if(
        completed_windows >=
        APP_CONF_MEASUREMENT_WINDOWS
      ) {

        LOG_INFO(
          "TRAFFIC_DONE,"
          "node=%u,"
          "windows=%u,"
          "tx_total=%lu,"
          "udp_sent_total=%lu\n",

          get_node_id(),

          completed_windows,

          (unsigned long)
          total_tx,

          (unsigned long)
          total_udp_sent
        );


        /*
         * Plus aucun trafic applicatif après
         * la 36e fenêtre.
         */
        PROCESS_EXIT();
      }


      /* =================================================== */
      /* FENETRE SUIVANTE                                    */
      /* =================================================== */

      current_window_id++;


      sent_this_window = 0;

      udp_sent_this_window = 0;


      send_delay_ticks =
        choose_send_delay();


      /*
       * On conserve des frontières de fenêtres
       * régulières de 600 secondes.
       */
      etimer_reset_with_new_interval(
        &window_timer,
        TRAFFIC_WINDOW_TICKS
      );


      etimer_set(
        &send_timer,
        send_delay_ticks
      );
    }
  }


  PROCESS_END();
}