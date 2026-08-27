#ifndef PROJECT_CONF_H_
#define PROJECT_CONF_H_

/* =========================================================
 * ENERGEST
 * ========================================================= */
#define ENERGEST_CONF_ON 1

/* =========================================================
 * RPL / TRICKLE
 * ========================================================= */
#define RPL_CONF_DIO_INTERVAL_MIN 10
#define RPL_CONF_DIO_INTERVAL_DOUBLINGS 6
#define RPL_CONF_DIO_REDUNDANCY 0

/* =========================================================
 * RPL OBJECTIVE FUNCTION
 * Tous les noeuds supportent OF0 et MRHOF.
 * Le root sélectionne l'OF utilisée.
 * ========================================================= */
#define RPL_CONF_SUPPORTED_OFS {&rpl_of0, &rpl_mrhof}
#define RPL_CONF_OF_OCP RPL_OCP_MRHOF

/* =========================================================
 * APPLICATION
 * Valeur en secondes
 * ========================================================= */
#define APP_CONF_SEND_INTERVAL 10

#endif /* PROJECT_CONF_H_ */
