#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
"""
Laurimate - Permanent Auto-Start Boot Launcher for SoftBank Pepper
Registered in /home/nao/naoqi/preferences/autoload.ini under [program].
Automatically launches the main Laurimate system and tablet UI when Pepper boots up.
"""

import os
import sys
import time
import socket
import subprocess

for _p in ["/opt/aldebaran/lib/python2.7/site-packages", "/usr/lib/python2.7/site-packages"]:
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
os.environ["PYTHONPATH"] = "/opt/aldebaran/lib/python2.7/site-packages:/usr/lib/python2.7/site-packages"

LAURIMATE_DIR = "/home/nao/Laurimate"
MAIN_SCRIPT = os.path.join(LAURIMATE_DIR, "pepper_main.py")
KIDS_SCRIPT = os.path.join(LAURIMATE_DIR, "kids_fun.py")
LOG_FILE = os.path.join(LAURIMATE_DIR, "laurimate_boot.log")
LOCK_PORT = 47831
TABLET_URL = "http://198.18.0.1/apps/laurimate-1e47c7/index.html"


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = "[{} BootLauncher] {}\n".format(ts, msg)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line)
    except Exception:
        pass


def acquire_single_instance_lock():
    """Bind a local loopback socket so only one boot watchdog ever runs at a time."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except Exception:
        return None


def wait_for_naoqi_services():
    """Wait until NAOqi core services and ALTabletService are ready after robot power-on."""
    from naoqi import ALProxy
    log("Waiting for NAOqi services on 127.0.0.1:9559...")
    for attempt in range(90):
        try:
            motion = ALProxy("ALMotion", "127.0.0.1", 9559)
            tts = ALProxy("ALTextToSpeech", "127.0.0.1", 9559)
            audio = ALProxy("ALAudioDevice", "127.0.0.1", 9559)
            if motion and tts and audio:
                log("Core NAOqi services ready (attempt {}).".format(attempt + 1))
                break
        except Exception:
            pass
        time.sleep(2.0)

    # Wait for chest tablet service to come online
    for attempt in range(45):
        try:
            tablet = ALProxy("ALTabletService", "127.0.0.1", 9559)
            if tablet:
                log("ALTabletService online (attempt {}).".format(attempt + 1))
                break
        except Exception:
            pass
        time.sleep(2.0)

    # Give the Android chest tablet browser a few seconds to finish initializing
    time.sleep(8.0)


def ensure_kids_touch_daemon():
    """Ensure kids_fun.py --daemon is listening on port 8765 for tablet touch controls."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        in_use = (s.connect_ex(("127.0.0.1", 8765)) == 0)
        s.close()
        if not in_use and os.path.exists(KIDS_SCRIPT):
            log("Starting kids_fun.py --daemon on port 8765...")
            subprocess.Popen(
                ["/usr/bin/python2.7", KIDS_SCRIPT, "--daemon"],
                cwd=LAURIMATE_DIR,
                stdout=open(os.devnull, "w"),
                stderr=open(os.devnull, "w"),
                close_fds=True
            )
    except Exception as e:
        log("Kids daemon start note: {}".format(e))


def is_pepper_main_running():
    """Check if pepper_main.py is already running."""
    try:
        out = subprocess.check_output(["ps", "aux"])
        for line in out.splitlines():
            if "pepper_main.py" in line and "grep" not in line:
                return True
    except Exception:
        pass
    return False


KIDS_FLAG = "/tmp/laurimate_kids_webview_v6.flag"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/prastikaac/Laurimate/main"
APP_ROOT_DIR = "/home/nao/.local/share/PackageManager/apps/laurimate-1e47c7"
APP_HTML_DIR = "/home/nao/.local/share/PackageManager/apps/laurimate-1e47c7/html"


def sync_latest_from_github():
    """
    Pulls latest pepper_main.py, kids_fun.py, and tablet UI files directly from GitHub
    over the internet on boot (works even on laurea-visitor with AP client isolation!).
    """
    files_to_sync = [
        ("pepper_main.py", [os.path.join(LAURIMATE_DIR, "pepper_main.py")], "# -*- coding: utf-8 -*-"),
        ("kids_fun.py",    [os.path.join(LAURIMATE_DIR, "kids_fun.py")],    "# -*- coding: utf-8 -*-"),
        ("tablet/index.html", [os.path.join(APP_ROOT_DIR, "index.html"), os.path.join(APP_HTML_DIR, "index.html")], "<!DOCTYPE html>"),
        ("tablet/kids.html",  [os.path.join(APP_ROOT_DIR, "kids.html"),  os.path.join(APP_HTML_DIR, "kids.html")],  "<!DOCTYPE html>"),
    ]
    for rel_url, dest_paths, valid_marker in files_to_sync:
        try:
            url = "{}/{}?t={}".format(GITHUB_RAW_BASE, rel_url, int(time.time()))
            p = subprocess.Popen(
                ["curl", "-k", "-s", "-L", "--max-time", "8", url],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            out, _ = p.communicate()
            if out and valid_marker in out and len(out) > 1000:
                out_lf = out.replace("\r\n", "\n")
                for dp in dest_paths:
                    try:
                        with open(dp, "wb") as f:
                            f.write(out_lf)
                    except Exception:
                        pass
                log("Synced latest {} from GitHub ({} bytes).".format(rel_url, len(out_lf)))
        except Exception as e:
            log("GitHub sync note for {}: {}".format(rel_url, e))


def main():
    lock_sock = acquire_single_instance_lock()
    if not lock_sock:
        log("BootLauncher already running; exiting duplicate instance.")
        return

    log("=== Pepper Boot Sequence Started ===")
    # On fresh boot, wait for NAOqi and ALTabletService
    wait_for_naoqi_services()

    # Supervise pepper_main.py forever (pauses automatically while Kids Mode is active)
    while True:
        if os.path.exists(KIDS_FLAG):
            # Kids Mode is currently active — keep pepper_main.py stopped so it doesn't interfere
            if is_pepper_main_running():
                log("Kids Mode active -> stopping pepper_main.py")
                os.system("pkill -f '[p]epper_main.py' >/dev/null 2>&1")
            time.sleep(3.0)
            continue

        if not is_pepper_main_running():
            log("Launching main Pepper system: pepper_main.py")
            try:
                log_fp = open(LOG_FILE, "a")
                proc = subprocess.Popen(
                    ["/usr/bin/python2.7", "-u", MAIN_SCRIPT],
                    cwd=LAURIMATE_DIR,
                    stdout=log_fp,
                    stderr=log_fp,
                    close_fds=True
                )
                proc.wait()
                log("pepper_main.py exited with code {}. Restarting in 5s...".format(proc.returncode))
            except Exception as e:
                log("Error running pepper_main.py: {}".format(e))
        time.sleep(5.0)


if __name__ == "__main__":
    main()
