# -*- coding: utf-8 -*-
"""
Configure Pepper Robot & Chest Tablet Wi-Fi via SSH (ALConnectionManager + ALTabletService)
Usage:
  python set_pepper_wifi.py --scan
  python set_pepper_wifi.py --connect "laurea-visitor" "wlanv1s1tor"
"""

import sys
import time
import paramiko

PEPPER_SSH_IP = "192.168.0.118"
PEPPER_USER   = "nao"
PEPPER_PASS   = "Dll#2025"

REMOTE_WIFI_HELPER = """#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import sys
import time
import subprocess
sys.path.insert(0, "/opt/aldebaran/lib/python2.7/site-packages")
from naoqi import ALProxy

LOG_PATH = "/home/nao/Laurimate/wifi_status.log"

def log(msg):
    line = "[{}] {}\\n".format(time.strftime("%H:%M:%S"), msg)
    sys.stdout.write(line)
    sys.stdout.flush()
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line)
    except Exception:
        pass

cm = ALProxy("ALConnectionManager", "127.0.0.1", 9559)
try:
    tablet = ALProxy("ALTabletService", "127.0.0.1", 9559)
except Exception:
    tablet = None
try:
    tts = ALProxy("ALTextToSpeech", "127.0.0.1", 9559)
except Exception:
    tts = None

mode = sys.argv[1] if len(sys.argv) > 1 else "scan"
cm.scan()
time.sleep(2.0)
services = cm.services()

if mode == "scan":
    print("VISIBLE WIFI NETWORKS ON PEPPER:")
    for s in services:
        d = dict(s)
        print("  SSID: {!r:25} | ServiceId: {:35} | State: {:10} | Security: {} | AutoConnect: {}".format(
            d.get("Name"), d.get("ServiceId"), d.get("State"), d.get("Security"), d.get("Favorite")
        ))
elif mode == "connect":
    target_ssid = sys.argv[2]
    target_pass = sys.argv[3]
    matched = None
    current_online = None
    for s in services:
        d = dict(s)
        name = str(d.get("Name") or "")
        if d.get("State") in ("online", "ready"):
            current_online = d
        if name.lower() == target_ssid.lower():
            matched = d

    if not matched:
        log("ERROR: SSID '{}' not found in scan!".format(target_ssid))
        sys.exit(1)

    sid = matched["ServiceId"]
    sec_list = matched.get("Security") or []
    log("Found '{}' -> ServiceId={} Security={}".format(matched.get("Name"), sid, sec_list))

    # 1. Configure chest tablet Wi-Fi as well
    if tablet:
        try:
            tablet.enableWifi()
            sec_type = "wpa"
            if "wep" in [str(x).lower() for x in sec_list]:
                sec_type = "wep"
            elif not sec_list or "none" in [str(x).lower() for x in sec_list]:
                sec_type = "open"
            ok_tab = tablet.configureWifi(sec_type, matched.get("Name"), target_pass)
            tablet.connectWifi(matched.get("Name"))
            log("Tablet Wi-Fi configured for '{}': {}".format(matched.get("Name"), ok_tab))
        except Exception as e:
            log("Tablet Wi-Fi note: {}".format(e))

    # 2. Configure ALConnectionManager Service Input/Configuration
    for fn_name in ("setServiceInput", "setServiceConfiguration"):
        try:
            fn = getattr(cm, fn_name)
            fn([
                ["ServiceId", sid],
                ["Passphrase", target_pass],
                ["AutoConnect", True]
            ])
            log("{} succeeded for {}".format(fn_name, sid))
        except Exception as e:
            log("{} note: {}".format(fn_name, e))

    # 3. Disconnect old service if different, then connect to target service
    if current_online and current_online.get("ServiceId") != sid:
        try:
            old_sid = current_online.get("ServiceId")
            log("Disconnecting from current Wi-Fi: {} ({})".format(current_online.get("Name"), old_sid))
            cm.disconnect(old_sid)
            time.sleep(1.5)
        except Exception as e:
            log("Disconnect note: {}".format(e))

    for attempt in range(3):
        try:
            log("Connecting to {} (attempt {})...".format(target_ssid, attempt + 1))
            cm.connect(sid)
        except Exception as e:
            log("cm.connect note: {}".format(e))

        # Re-supply passphrase if requested during handshake
        for _ in range(8):
            time.sleep(1.0)
            try:
                cm.setServiceInput([["ServiceId", sid], ["Passphrase", target_pass]])
            except Exception:
                pass
            try:
                st = dict(cm.service(sid)).get("State", "")
                if st in ("online", "ready"):
                    break
            except Exception:
                pass

        try:
            svc_now = dict(cm.service(sid))
            st_now = svc_now.get("State", "")
            log("Service state after attempt {}: {}".format(attempt + 1, st_now))
            if st_now in ("online", "ready"):
                break
        except Exception:
            pass

    # Check new IP address
    time.sleep(2.0)
    ip_addr = ""
    try:
        out = subprocess.check_output(["ip", "-4", "addr", "show", "wlan0"])
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                ip_addr = line.split()[1].split("/")[0]
                break
    except Exception:
        pass

    svc_final = dict(cm.service(sid))
    final_state = svc_final.get("State", "")
    log("Final state for '{}': {} | wlan0 IP: {}".format(target_ssid, final_state, ip_addr))

    if final_state in ("online", "ready") and ip_addr:
        if tts:
            try:
                tts.say("Connected to Wi-Fi " + str(target_ssid) + ". My IP address is " + " ".join(ip_addr.replace(".", " dot ").split()))
            except Exception:
                pass
    else:
        log("WARNING: Could not reach online/ready on '{}'. Reconnecting fallback Wi-Fi...".format(target_ssid))
        if current_online and current_online.get("ServiceId"):
            try:
                cm.connect(current_online.get("ServiceId"))
            except Exception:
                pass
"""


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(PEPPER_SSH_IP, username=PEPPER_USER, password=PEPPER_PASS, timeout=10)

    sftp = ssh.open_sftp()
    with sftp.open("/home/nao/Laurimate/wifi_helper.py", "wb") as f:
        f.write(REMOTE_WIFI_HELPER.replace("\r\n", "\n").encode("utf-8"))
    sftp.close()

    if len(sys.argv) >= 4 and sys.argv[1] == "--connect":
        ssid = sys.argv[2]
        pw = sys.argv[3]
        print("Triggering Wi-Fi switch on Pepper to SSID '{}'...".format(ssid))
        print("(Note: Once Pepper disconnects from 192.168.0.118 to join '{}', Pepper will speak its new IP address out loud!)".format(ssid))
        cmd = 'setsid python2.7 /home/nao/Laurimate/wifi_helper.py connect "{}" "{}" </dev/null >/home/nao/Laurimate/wifi_switch.out 2>&1 & sleep 2 && cat /home/nao/Laurimate/wifi_switch.out'.format(ssid, pw)
    else:
        cmd = "python2.7 /home/nao/Laurimate/wifi_helper.py scan"

    _, out, err = ssh.exec_command(cmd)
    print(out.read().decode("utf-8", "ignore"))
    e = err.read().decode("utf-8", "ignore")
    if e:
        print(e)
    ssh.close()


if __name__ == "__main__":
    main()
