import re
import os

def generate_simulation():
    csc_base = "rpl-udp-cooja.csc"
    csc_out = "simulation_rpl.csc"

    if not os.path.exists(csc_base):
        print(f"[!] Fichier de base {csc_base} introuvable.")
        return

    with open(csc_base, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Injection du ScriptRunner (Timeout + log.testOK)
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
    new_content = content.replace("</simconf>", script_plugin)

    # 2. Injection d'une perte radio réaliste dans UDGM (PDR variable)
    if "<org.contikios.cooja.radiomediums.UDGM>" in new_content:
        udgm_config = """<org.contikios.cooja.radiomediums.UDGM>
        <transmitting_range>50.0</transmitting_range>
        <interference_range>100.0</interference_range>
        <success_ratio_tx>0.95</success_ratio_tx>
        <success_ratio_rx>0.88</success_ratio_rx>
      </org.contikios.cooja.radiomediums.UDGM>"""
        new_content = re.sub(r'<org\.contikios\.cooja\.radiomediums\.UDGM\/>', udgm_config, new_content)

    with open(csc_out, "w", encoding="utf-8") as f:
        f.write(new_content)

    print("[+] Fichier simulation_rpl.csc mis à jour (ScriptRunner + Taux de perte UDGM injectés) !")

if __name__ == "__main__":
    generate_simulation()