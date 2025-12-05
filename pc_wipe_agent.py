import os
import threading
import shutil
import psutil
from flask import Flask, request, jsonify

API_KEY = "admin"

app = Flask(__name__)

# Thread-safe tracking of all active wipe threads
active_wipes = {}          # thread_ident → {'stop_flag': Event(), 'path': str, 'progress': int}
wipes_lock = threading.Lock()

def delete_contents(path):
    try:
        for item in os.listdir(path):
            item_path = os.path.join(path, item)
            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.unlink(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
            except Exception as e:
                print(f"[ERROR] Failed to delete {item_path}: {e}")
    except Exception as e:
        print(f"[ERROR] Could not list {path}: {e}")

def wipe_worker(path, method):
    thread_id = threading.get_ident()
    stop_event = threading.Event()

    with wipes_lock:
        active_wipes[thread_id] = {
            "stop_flag": stop_event,
            "path": path,
            "progress": 0
        }

    print(f"[WIPE {thread_id}] Starting → {path} ({method})")

    # Step 1: Delete everything
    delete_contents(path)

    # Step 2: Fill free space with a temporary file that is GUARANTEED to be removed
    wipe_file = os.path.join(path, ".wipe_temp_fill.bin")
    try:
        total_free = psutil.disk_usage(path).free
        block_size = 200 * 1024 * 1024  # 200 MB blocks
        written = 0

        with open(wipe_file, "wb") as f:
            while written < total_free and not stop_event.is_set():
                chunk = block_size
                if written + chunk > total_free:
                    chunk = total_free - written

                if method == "zero":
                    f.write(b"\x00" * chunk)
                else:
                    f.write(os.urandom(chunk))

                written += chunk
                progress = int((written / total_free) * 100) if total_free > 0 else 100

                with wipes_lock:
                    if thread_id in active_wipes:
                        active_wipes[thread_id]["progress"] = progress

        print(f"[WIPE {thread_id}] {'Stopped' if stop_event.is_set() else 'Completed'}")

    except Exception as e:
        print(f"[WIPE {thread_id}] Exception: {e}")

    finally:
        # ALWAYS remove the fill file, even on crash/power-off (as long as process exits cleanly)
        try:
            if os.path.exists(wipe_file):
                os.remove(wipe_file)
                print(f"[WIPE {thread_id}] Cleanup: {wipe_file} removed")
        except:
            pass

        # Remove from active list
        with wipes_lock:
            active_wipes.pop(thread_id, None)


# ============================ ROUTES ============================

@app.route("/status")
def status():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    with wipes_lock:
        any_active = len(active_wipes) > 0

    return jsonify({
        "status": "online",
        "wipe_active": any_active
    })


@app.route("/list-devices")
def list_devices():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    drives = []
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            drives.append({
                "device": part.device,
                "mount": part.mountpoint,
                "fs": part.fstype,
                "total_gb": round(usage.total / (1024**3), 2)
            })
        except:
            continue
    return jsonify({"devices": drives})


@app.route("/wipe", methods=["POST"])
def wipe():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    path = request.args.get("device", "").strip()
    method = request.args.get("method", "zero").lower()
    if method not in ["zero", "random"]:
        method = "zero"

    if not path or not os.path.exists(path):
        return jsonify({"error": "Invalid or missing device path"}), 400

    # Start a new independent thread — no global blocking anymore
    t = threading.Thread(target=wipe_worker, args=(path, method), daemon=False)
    t.start()

    return jsonify({
        "status": "wipe_started",
        "path": path,
        "method": method
    })


@app.route("/emergency-stop", methods=["POST"])
def emergency_stop():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    stopped = 0
    with wipes_lock:
        for info in active_wipes.values():
            info["stop_flag"].set()
            stopped += 1

    return jsonify({"status": "stopping", "stopped_wipes": stopped})


if __name__ == "__main__":
    print("========================================")
    print(" PC WIPE AGENT (Linux) – Multi-PC Ready")
    print(" No leftover files – Fully compatible with your Android app")
    print(" Listening on http://0.0.0.0:5050")
    print("========================================")
    app.run(host="0.0.0.0", port=5050, threaded=True)
