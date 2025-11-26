import os
import threading
import subprocess
import psutil
import shutil
from flask import Flask, request, jsonify

API_KEY = "admin"
stop_flag = False
wipe_process = None

app = Flask(__name__)

# ----------------------------
# AUTH CHECK
# ----------------------------
def check_auth(request):
    key = request.headers.get("X-API-Key", "")
    return key == API_KEY

# ----------------------------
# LIST LINUX MOUNTED DEVICES
# ----------------------------
def list_drives():
    drives = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except PermissionError:
            continue

        drives.append({
            "device": part.device,
            "mount": part.mountpoint,
            "fs": part.fstype,
            "total_gb": round(usage.total / (1024**3), 2)
        })
    return drives

def delete_contents(path):
    for item in os.listdir(path):
        item_path = os.path.join(path, item)
        try:
            if os.path.isfile(item_path) or os.path.islink(item_path):
                os.remove(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)
        except Exception as e:
            print("[ERROR] Could not delete:", item_path, e)
# ----------------------------
# WIPE FUNCTION
# ----------------------------
def wipe_device(path, method):
    global stop_flag
    stop_flag = False

    print(f"[INFO] Starting wipe on {path} with method {method}")

    if not os.path.exists(path):
        print("[ERROR] Path does not exist:", path)
        return

    # SAFE — remove all files
    delete_contents(path)

    wipe_file = os.path.join(path, "wipe_fill.bin")

    try:
        total_bytes = psutil.disk_usage(path).free
        block_size = 200 * 1024 * 1024

        with open(wipe_file, "wb") as f:
            written = 0
            while written < total_bytes:
                if stop_flag:
                    print("[INFO] Emergency stop triggered")
                    break

                if method == "zero":
                    f.write(b"\x00" * block_size)
                else:
                    f.write(os.urandom(block_size))
                written += block_size

        print("[INFO] Wipe completed")

    except Exception as e:
        print("[ERROR]", e)

    finally:
        if os.path.exists(wipe_file):
            os.remove(wipe_file)

# ----------------------------
# API ROUTES
# ----------------------------
@app.route("/status")
def status():
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"status": "online"})

@app.route("/list-devices")
def devices():
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"devices": list_drives()})

@app.route("/wipe", methods=["POST"])
def wipe():
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401

    path = request.args.get("device", "")
    method = request.args.get("method", "zero")

    if path == "":
        return jsonify({"error": "Missing device"}), 400

    global wipe_process
    wipe_process = threading.Thread(target=wipe_device, args=(path, method))
    wipe_process.start()

    return jsonify({"status": "wipe_started", "path": path, "method": method})

@app.route("/emergency-stop", methods=["POST"])
def emergency_stop():
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401

    global stop_flag
    stop_flag = True
    return jsonify({"status": "stopping"})

# ----------------------------
# START SERVER
# ----------------------------
if __name__ == "__main__":
    print("========================================")
    print(" PC WIPE AGENT (Linux)")
    print(" Listening on http://0.0.0.0:5050")
    print(" API KEY:", API_KEY)
    print("========================================")
    app.run(host="0.0.0.0", port=5050)
