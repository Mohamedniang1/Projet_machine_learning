/*
 * udp-server.c
 *
 * Root RPL / serveur UDP de la nouvelle campagne.
 *
 * Plateforme :
 * - Contiki-NG
 * - RPL-Lite
 * - Sky / Tmote Sky
 * - CC2420
 *
 * Fonctionnement :
 * - démarre comme root RPL ;
 * - reçoit les paquets de 10 octets envoyés par les 35 clients ;
 * - ne renvoie aucun echo ;
 * - journalise chaque réception pour calculer PDR et délai ;
 * - collecte Energest pour le root toutes les 600 secondes.
 */

#include "contiki.h"

#include "net/routing/routing.h"
#include "net/netstack.h"

#include "net/ipv6/simple-udp.h"
#include "net/packetbuf.h"

#include "dev/radio.h"

#include "sys/energest.h"
#include "sys/log.h"

#include <inttypes.h>
#include <stdint.h>


/* ========================================================= */
/* CONFIGURATION                                              */
/* ========================================================= */

#define LOG_MODULE "App"
#define LOG_LEVEL LOG_LEVEL_INFO

#define UDP_CLIENT_PORT 8765
#define UDP_SERVER_PORT 5678


/* --------------------------------------------------------- */
/* Fenêtre expérimentale                                     */
/* --------------------------------------------------------- */

#ifndef APP_CONF_TRAFFIC_WINDOW_SECONDS
#define APP_CONF_TRAFFIC_WINDOW_SECONDS 600
#endif


/* --------------------------------------------------------- */
/* Phase initiale de convergence                             */
/* --------------------------------------------------------- */

#ifndef APP_CONF_TRAFFIC_START_SECONDS
#define APP_CONF_TRAFFIC_START_SECONDS 600
#endif


/* --------------------------------------------------------- */
/* Payload                                                   */
/* --------------------------------------------------------- */

#ifndef APP_CONF_PAYLOAD_SIZE
#define APP_CONF_PAYLOAD_SIZE 10
#endif


#if APP_CONF_PAYLOAD_SIZE != 10
#error "APP_CONF_PAYLOAD_SIZE doit etre exactement egal a 10"
#endif


/* --------------------------------------------------------- */
/* Puissance CC2420                                          */
/* --------------------------------------------------------- */

#ifndef APP_CONF_TX_POWER_DBM
#define APP_CONF_TX_POWER_DBM 0
#endif


/* --------------------------------------------------------- */
/* Timers                                                    */
/* --------------------------------------------------------- */

#define TRAFFIC_WINDOW_TICKS \
  ((clock_time_t)APP_CONF_TRAFFIC_WINDOW_SECONDS * CLOCK_SECOND)

#define TRAFFIC_START_TICKS \
  ((clock_time_t)APP_CONF_TRAFFIC_START_SECONDS * CLOCK_SECOND)


/* --------------------------------------------------------- */
/* Signature payload                                         */
/* --------------------------------------------------------- */

#define PAYLOAD_MAGIC_0 0x52
#define PAYLOAD_MAGIC_1 0x50


/* ========================================================= */
/* PROCESSUS                                                  */
/* ========================================================= */

PROCESS(
  udp_server_process,
  "RPL root UDP server"
);

AUTOSTART_PROCESSES(
  &udp_server_process
);


/* ========================================================= */
/* UDP                                                        */
/* ========================================================= */

static struct simple_udp_connection udp_conn;


/* ========================================================= */
/* COMPTEURS                                                  */
/* ========================================================= */

static uint32_t total_rx;

static uint32_t rx_current_window;

static uint32_t current_window_id;


/* ========================================================= */
/* ENERGEST                                                   */
/* ========================================================= */

static uint64_t previous_cpu;

static uint64_t previous_lpm;

static uint64_t previous_deep_lpm;

static uint64_t previous_tx;

static uint64_t previous_listen;

static uint64_t previous_total_time;


/* ========================================================= */
/* PUISSANCE RADIO                                            */
/* ========================================================= */

static void
configure_tx_power(void)
{
  radio_value_t actual_power;


  if(
    NETSTACK_RADIO.set_value(
      RADIO_PARAM_TXPOWER,
      (radio_value_t)
      APP_CONF_TX_POWER_DBM
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
/* DÉCODAGE DU PAYLOAD                                       */
/* ========================================================= */

static uint16_t
payload_source_id(
  const uint8_t *data
)
{
  return
    (
      ((uint16_t)data[2]) << 8
    )
    |
    (uint16_t)data[3];
}


static uint16_t
payload_sequence(
  const uint8_t *data
)
{
  return
    (
      ((uint16_t)data[4]) << 8
    )
    |
    (uint16_t)data[5];
}


static uint32_t
payload_window_id(
  const uint8_t *data
)
{
  return
    (((uint32_t)data[6]) << 24)
    |
    (((uint32_t)data[7]) << 16)
    |
    (((uint32_t)data[8]) << 8)
    |
    ((uint32_t)data[9]);
}


/* ========================================================= */
/* INITIALISATION ENERGEST                                   */
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
/* SUMMARY DU ROOT                                           */
/* ========================================================= */

static void
print_root_summary(void)
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


  energest_flush();


  /* ------------------------------------------------------- */
  /* Lecture Energest                                        */
  /* ------------------------------------------------------- */

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


  /* ------------------------------------------------------- */
  /* Deltas                                                  */
  /* ------------------------------------------------------- */

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


  /* ------------------------------------------------------- */
  /* Mise à jour des références                              */
  /* ------------------------------------------------------- */

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
  /* Log                                                     */
  /* ------------------------------------------------------- */

  LOG_INFO(
    "ROOT_SUMMARY,"
    "time=%lu,"
    "window=%lu,"
    "rx_total=%lu,"
    "rx_window=%lu,"
    "cpu_ticks=%" PRIu64 ","
    "lpm_ticks=%" PRIu64 ","
    "deep_lpm_ticks=%" PRIu64 ","
    "radio_tx_ticks=%" PRIu64 ","
    "radio_listen_ticks=%" PRIu64 ","
    "total_time_ticks=%" PRIu64 "\n",

    (unsigned long)
    clock_seconds(),

    (unsigned long)
    current_window_id,

    (unsigned long)
    total_rx,

    (unsigned long)
    rx_current_window,

    cpu_delta,

    lpm_delta,

    deep_lpm_delta,

    tx_delta,

    listen_delta,

    total_time_delta
  );
}


/* ========================================================= */
/* RÉCEPTION UDP                                              */
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
  uint16_t source_id;

  uint16_t sequence;

  uint32_t window_id;

  int16_t rssi;


  (void)c;

  (void)sender_addr;

  (void)sender_port;

  (void)receiver_addr;

  (void)receiver_port;


  /* ======================================================= */
  /* VÉRIFICATION DE LA TAILLE                               */
  /* ======================================================= */

  if(
    data == NULL
    ||
    datalen !=
      APP_CONF_PAYLOAD_SIZE
  ) {

    return;
  }


  /* ======================================================= */
  /* VÉRIFICATION SIGNATURE                                  */
  /* ======================================================= */

  if(
    data[0] !=
      PAYLOAD_MAGIC_0
    ||
    data[1] !=
      PAYLOAD_MAGIC_1
  ) {

    return;
  }


  /* ======================================================= */
  /* DÉCODAGE                                                */
  /* ======================================================= */

  source_id =
    payload_source_id(
      data
    );


  sequence =
    payload_sequence(
      data
    );


  window_id =
    payload_window_id(
      data
    );


  /* ======================================================= */
  /* RSSI                                                    */
  /* ======================================================= */

  rssi =
    (int16_t)
    packetbuf_attr(
      PACKETBUF_ATTR_RSSI
    );


  /* ======================================================= */
  /* COMPTEURS                                               */
  /* ======================================================= */

  total_rx++;


  /*
   * Ce compteur correspond aux paquets
   * effectivement reçus pendant la fenêtre
   * temporelle actuelle du root.
   */
  rx_current_window++;


  /* ======================================================= */
  /* LOG RX                                                  */
  /* ======================================================= */

  /*
   * Le timestamp global ajouté par Cooja à cette ligne
   * sera comparé au timestamp du TX correspondant.
   *
   * Clé unique :
   *
   * source_id + sequence + window_id
   */
  LOG_INFO(
    "RX,"
    "node=%u,"
    "seq=%u,"
    "window=%lu,"
    "rssi=%d\n",

    source_id,

    sequence,

    (unsigned long)
    window_id,

    rssi
  );


  /*
   * IMPORTANT :
   *
   * aucun echo n'est envoyé.
   */
}


/* ========================================================= */
/* PROCESSUS PRINCIPAL                                       */
/* ========================================================= */

PROCESS_THREAD(
  udp_server_process,
  ev,
  data
)
{
  static struct etimer
    warmup_timer;


  static struct etimer
    window_timer;


  PROCESS_BEGIN();


  /* ======================================================= */
  /* INITIALISATION                                          */
  /* ======================================================= */

  total_rx =
    0;


  rx_current_window =
    0;


  current_window_id =
    0;


  /* ======================================================= */
  /* CC2420                                                  */
  /* ======================================================= */

  configure_tx_power();


  /* ======================================================= */
  /* ROOT RPL                                                */
  /* ======================================================= */

  NETSTACK_ROUTING.
    root_start();


  /* ======================================================= */
  /* UDP                                                     */
  /* ======================================================= */

  simple_udp_register(
    &udp_conn,

    UDP_SERVER_PORT,

    NULL,

    UDP_CLIENT_PORT,

    udp_rx_callback
  );


  LOG_INFO(
    "ROOT_START\n"
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
   * On exclut également la convergence
   * de l'énergie expérimentale du root.
   */
  initialize_energest_reference();


  current_window_id =
    0;


  rx_current_window =
    0;


  LOG_INFO(
    "TRAFFIC_START_ROOT\n"
  );


  /* ======================================================= */
  /* FENÊTRES DE 600 s                                       */
  /* ======================================================= */

  etimer_set(
    &window_timer,
    TRAFFIC_WINDOW_TICKS
  );


  while(1) {

    PROCESS_WAIT_EVENT();


    if(
      etimer_expired(
        &window_timer
      )
    ) {

      /*
       * Résumé énergétique de la fenêtre
       * qui vient de se terminer.
       */
      print_root_summary();


      /*
       * Fenêtre suivante.
       */
      current_window_id++;


      rx_current_window =
        0;


      etimer_reset_with_new_interval(
        &window_timer,
        TRAFFIC_WINDOW_TICKS
      );
    }
  }


  PROCESS_END();
}