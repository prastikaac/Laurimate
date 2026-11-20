# -*- coding: utf-8 -*-
"""
Laurimate - Permanent On-Robot Installer (deploy_forever.py)
Uploads all Laurimate Python files, databases, and tablet UI files to Pepper's
permanent internal storage and configures /home/nao/naoqi/preferences/autoload.ini
so the system launches automatically every time Pepper is powered on.
"""

import os
import sys
import time
import paramiko

PEPPER_SSH_IP = "192.168.0.118"
PEPPER_USER   = "nao"
PEPPER_PASS   = "Dll#2025"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

REMOTE_LAURIMATE_DIR = "/home/nao/Laurimate"
REMOTE_APP_ROOT      = "/home/nao/.local/share/PackageManager/apps/laurimate-1e47c7"
REMOTE_APP_HTML      = "/home/nao/.local/share/PackageManager/apps/laurimate-1e47c7/html"
REMOTE_AUTOLOAD_INI  = "/home/nao/naoqi/preferences/autoload.ini"


def upload_file(sftp, local_path, remote_path, force_lf=False):
    with open(local_path, "rb") as f:
        data = f.read()
    if force_lf:
        data = data.replace(b"\r\n", b"\n")
    with sftp.open(remote_path, "wb") as rf:
        rf.write(data)
    print("  [Uploaded] {} -> {} ({} bytes)".format(os.path.basename(local_path), remote_path, len(data)))


def run_remote(ssh, cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode("utf-8", "ignore").strip()
    err = stderr.read().decode("utf-8", "ignore").strip()
    return out, err


def main():
    print("==================================================================")
    print(" Deploying Laurimate & Tablet Files Permanently to Pepper ({})".format(PEPPER_SSH_IP))
    print("==================================================================")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(PEPPER_SSH_IP, username=PEPPER_USER, password=PEPPER_PASS, timeout=12)
    sftp = ssh.open_sftp()

    # 1. Ensure remote directories exist
    run_remote(ssh, "mkdir -p {} {} {} /home/nao/naoqi/preferences".format(
        REMOTE_LAURIMATE_DIR, REMOTE_APP_ROOT, REMOTE_APP_HTML
    ))

    # 2. Upload core Python & data files to /home/nao/Laurimate/
    print("\n1) Uploading main Pepper system files to {}...".format(REMOTE_LAURIMATE_DIR))
    main_files = [
        ("pepper_main.py", True),
        ("kids_fun.py", True),
        ("start_on_boot.py", True),
        ("ai_wrapper.py", True),
        ("campus_faq.json", False),
        ("ansdatabase.json", False),
    ]
    for fname, is_text in main_files:
        lpath = os.path.join(BASE_DIR, fname)
        if os.path.exists(lpath):
            upload_file(sftp, lpath, "{}/{}".format(REMOTE_LAURIMATE_DIR, fname), force_lf=is_text)

    # Also upload functions/data/campus.json if present locally
    local_campus_json = os.path.join(BASE_DIR, "functions", "data", "campus.json")
    if os.path.exists(local_campus_json):
        upload_file(sftp, local_campus_json, "{}/campus.json".format(REMOTE_LAURIMATE_DIR), force_lf=False)

    # Make start_on_boot.py, pepper_main.py, kids_fun.py executable
    run_remote(ssh, "chmod +x {0}/start_on_boot.py {0}/pepper_main.py {0}/kids_fun.py".format(REMOTE_LAURIMATE_DIR))

    # 3. Upload all tablet UI files to both app root and html/ directory
    print("\n2) Uploading all tablet files to {} and {}...".format(REMOTE_APP_ROOT, REMOTE_APP_HTML))
    tablet_dir = os.path.join(BASE_DIR, "tablet")
    for fname in os.listdir(tablet_dir):
        lpath = os.path.join(tablet_dir, fname)
        if os.path.isfile(lpath):
            is_text = fname.endswith((".html", ".css", ".js", ".json"))
            upload_file(sftp, lpath, "{}/{}".format(REMOTE_APP_ROOT, fname), force_lf=is_text)
            upload_file(sftp, lpath, "{}/{}".format(REMOTE_APP_HTML, fname), force_lf=is_text)

    # 4. Configure /home/nao/naoqi/preferences/autoload.ini so Pepper auto-launches on power-on
    print("\n3) Configuring permanent auto-boot in {}...".format(REMOTE_AUTOLOAD_INI))
    autoload_content = (
        "# autoload.ini\n"
        "#\n"
        "# Use this file to list the cross-compiled modules that you wish to load.\n"
        "# You must specify the full path to the module, python module or program.\n"
        "\n"
        "[user]\n"
        "#the/full/path/to/your/liblibraryname.so  # load liblibraryname.so\n"
        "\n"
        "[python]\n"
        "#the/full/path/to/your/python_module.py   # load python_module.py\n"
        "\n"
        "[program]\n"
        "/home/nao/Laurimate/start_on_boot.py\n"
    )
    with sftp.open(REMOTE_AUTOLOAD_INI, "wb") as af:
        af.write(autoload_content.encode("utf-8"))
    print("  [Configured] /home/nao/Laurimate/start_on_boot.py added under [program] in autoload.ini")

    # 5. Restart background services cleanly so the new permanent setup is live immediately
    print("\n4) Starting permanent boot watchdog & main Pepper system on Pepper...")
    run_remote(ssh, "pkill -f start_on_boot.py; pkill -f pepper_main.py; truncate -s 0 /home/nao/Laurimate/laurimate_boot.log; rm -f /tmp/laurimate_kids_webview_v6.flag")
    time.sleep(1.0)
    run_remote(ssh, "setsid /home/nao/Laurimate/start_on_boot.py </dev/null >/dev/null 2>&1 &")
    time.sleep(12.0)

    out, _ = run_remote(ssh, "ps aux | grep -E 'start_on_boot|pepper_main|kids_fun' | grep -v grep && echo ===AUTOLOAD=== && cat /home/nao/naoqi/preferences/autoload.ini && echo ===BOOTLOG=== && cat /home/nao/Laurimate/laurimate_boot.log")
    print("\n5) Verification on Pepper:")
    print(out)

    sftp.close()
    ssh.close()
    print("\n==================================================================")
    print(" DONE! All files and auto-boot are permanently installed on Pepper.")
    print("==================================================================")


if __name__ == "__main__":
    main()
