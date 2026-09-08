#ifndef PROJECT_CONF_H_
#define PROJECT_CONF_H_

/* =========================================================
 * ENERGEST
 * ========================================================= */
#define ENERGEST_CONF_ON 1

/* =========================================================
 * RPL / TRICKLE - VARIABLES EXPERIMENTALES
 * ========================================================= */
#define RPL_CONF_DIO_INTERVAL_MIN 12
#define RPL_CONF_DIO_INTERVAL_DOUBLINGS 8
#define RPL_CONF_DIO_REDUNDANCY 1

/* =========================================================
 * OBJECTIVE FUNCTION - VARIABLE EXPERIMENTALE
 * ========================================================= */
#define RPL_CONF_SUPPORTED_OFS {&rpl_of0, &rpl_mrhof}
#define RPL_CONF_OF_OCP RPL_OCP_OF0

/* =========================================================
 * PROBING - VARIABLE EXPERIMENTALE
 * ========================================================= */
#define RPL_CONF_WITH_PROBING 1
#define RPL_CONF_PROBING_INTERVAL (90 * CLOCK_SECOND)
/* =========================================================
 * ROUTE LIFETIME - FIXE
 * 0xFF = infinite lifetime dans RPL-Lite
 * ========================================================= */
#define RPL_CONF_DEFAULT_LIFETIME 0xFF
#define RPL_CONF_DEFAULT_LIFETIME_UNIT 60

/* =========================================================
 * TRAFIC APPLICATIF - FIXE
 * 1 paquet/client/fenetre de 600 s, payload 10 octets
 * ========================================================= */
#define APP_CONF_TRAFFIC_WINDOW_SECONDS 600
#define APP_CONF_TRAFFIC_START_SECONDS 600
#define APP_CONF_MEASUREMENT_WINDOWS 36
#define APP_CONF_PAYLOAD_SIZE 10

/* =========================================================
 * CC2420 TX POWER - VARIABLE EXPERIMENTALE, en dBm
 * ========================================================= */
#define APP_CONF_TX_POWER_DBM 0

#endif /* PROJECT_CONF_H_ */
