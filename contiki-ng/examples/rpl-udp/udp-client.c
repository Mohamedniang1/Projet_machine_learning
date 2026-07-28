#include "contiki.h"
#include "net/routing/routing.h"
#include "random.h"
#include "net/netstack.h"
#include "net/ipv6/simple-udp.h"
#include "net/packetbuf.h"
#include "sys/log.h"

#define LOG_MODULE "App"
#define LOG_LEVEL LOG_LEVEL_INFO

#define UDP_CLIENT_PORT 8765
#define UDP_SERVER_PORT 5678
#define SEND_INTERVAL (10 * CLOCK_SECOND)

static struct simple_udp_connection udp_conn;
static uint32_t rx_count = 0;
static uint32_t tx_count = 0;

/* Structure du message échange */
struct data_packet {
  uint32_t seq;
  clock_time_t tx_time;
};

PROCESS(udp_client_process, "UDP client process");
AUTOSTART_PROCESSES(&udp_client_process);

static void
udp_rx_callback(struct simple_udp_connection *c,
                const uip_ipaddr_t *sender_addr,
                uint16_t sender_port,
                const uip_ipaddr_t *receiver_addr,
                uint16_t receiver_port,
                const uint8_t *data,
                uint16_t datalen)
{
  if(datalen == sizeof(struct data_packet)) {
    struct data_packet *pkt = (struct data_packet *)data;
    rx_count++;
    
    clock_time_t now = clock_time();
    clock_time_t rtt_ticks = now - pkt->tx_time;
    uint32_t rtt_ms = (uint32_t)((rtt_ticks * 1000UL) / CLOCK_SECOND);
    int8_t rssi = (int8_t)packetbuf_attr(PACKETBUF_ATTR_RSSI);

    /* Impression de la métrique avec RTT exact */
    LOG_INFO("METRIC,node=%u,seq=%"PRIu32",rssi=%d,delay=%"PRIu32"\n",
             linkaddr_node_addr.u8[LINKADDR_SIZE - 1], pkt->seq, rssi, rtt_ms);
  }
}

PROCESS_THREAD(udp_client_process, ev, data)
{
  static struct etimer periodic_timer;
  static uip_ipaddr_t dest_ipaddr;
  static struct data_packet pkt;

  PROCESS_BEGIN();

  /* LOG CANARI : Preuve de recompilation du client */
  LOG_INFO("[CANARY_v2.0_CLIENT] Initialisation du client avec RTT exact\n");

  simple_udp_register(&udp_conn, UDP_CLIENT_PORT, NULL,
                      UDP_SERVER_PORT, udp_rx_callback);

  etimer_set(&periodic_timer, random_rand() % SEND_INTERVAL);

  while(1) {
    PROCESS_WAIT_EVENT_UNTIL(etimer_expired(&periodic_timer));

    if(NETSTACK_ROUTING.node_is_reachable() && NETSTACK_ROUTING.get_root_ipaddr(&dest_ipaddr)) {
      tx_count++;
      pkt.seq = tx_count;
      pkt.tx_time = clock_time();

      simple_udp_sendto(&udp_conn, &pkt, sizeof(pkt), &dest_ipaddr);
    }

    etimer_set(&periodic_timer, SEND_INTERVAL + (random_rand() % (CLOCK_SECOND * 2)));
  }

  PROCESS_END();
}