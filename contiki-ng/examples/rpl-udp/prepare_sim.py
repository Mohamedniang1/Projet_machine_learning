import re

# Lire le fichier officiel de Contiki-NG
with open("rpl-udp-cooja.csc", "r", encoding="utf-8") as f:
    content = f.read()

# Bloc du plugin ScriptRunner avec un Timeout de 1h (3600000 ms)
script_plugin = """
  <plugin>
    org.contikios.cooja.plugins.ScriptRunner
    <plugin_config>
      <script>
        TIMEOUT(3600000, log.testOK());
        while (true) {
          log.log(time + " " + id + " " + msg + "\\n");
          YIELD();
        }
      </script>
      <active>true</active>
    </plugin_config>
    <width>600</width>
    <z>1</z>
    <height>700</height>
    <location_x>600</location_x>
    <location_y>0</location_y>
  </plugin>
</simconf>
"""

# Inserer le plugin juste avant la fermeture </simconf>
new_content = content.replace("</simconf>", script_plugin)

with open("simulation_rpl.csc", "w", encoding="utf-8") as f:
    f.write(new_content)

print("[+] Fichier simulation_rpl.csc prêt avec Timeout !") 