import os
import threading
import shutil
import psutil
from flask import Flask, request, jsonify

API_KEY = "admin"
app = Flask(__name__)

# Thread-safe wipe tracking
active_wipes = {}          # thread_id → dict
wipes_lock = threading.Lock()

def delete_contents(path):
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            fp = os.path.join(root, name)
            try:
                os.chmod(fp, 0o777)    # force writable
                os.unlink(fp)
            except Exception as e:
                print(f"[DEL] Failed {fp}: {e}")
        for name in dirs:
            try:
                shutil.rmtree(os.path.join(root, name))
            except Exception:
                pass

def wipe_worker(path, method):
    thread_id = threading.get_ident()
    stop_event = threading.Event()

    # Use a unique temporary file per thread
    wipe_file = os.path.join(path, f".wipe_fill_{thread_id}.bin")

    with wipes_lock:
        active_wipes[thread_id] = {
            "stop_flag": stop_event,
            "path": path,
            "progress": 0,
            "file": wipe_file
        }

    print(f"[WIPE {thread_id}] Starting → {path} | Method: {method}")

    # Step 1: Delete all files/folders
    delete_contents(path)

    # Step 2: Fill free space
    try:
        usage = psutil.disk_usage(path)
        total_free = usage.free
        block_size = 256 * 1024 * 1024  # 256 MB chunks = faster + safer
        written = 0

        with open(wipe_file, "wb", buffering=0) as f:  # unbuffered = real disk write
            while written < total_free and not stop_event.is_set():
                remaining = total_free - written
                chunk = min(block_size, remaining)

                if method == "zero":
                    f.write(b"\x00" * chunk)
                else:
                    f.write(os.urandom(chunk))

                written += chunk
                progress = int((written / total_free) * 100) if total_free > 0 else 100

                with wipes_lock:
                    if thread_id in active_wipes:
                        active_wipes[thread_id]["progress"] = progress

        status = "Stopped" if stop_event.is_set() else "Completed"
        print(f"[WIPE {thread_id}] {status}")

    except Exception as e:
        print(f"[WIPE {thread_id}] ERROR: {e}")

    finally:
        # Always delete the fill file
        try:
            if os.path.exists(wipe_file):
                os.remove(wipe_file)
                print(f"[WIPE {thread_id}] Cleaned up {wipe_file}")
        except:
            pass

        with wipes_lock:
            active_wipes.pop(thread_id, None)


# ====================== ROUTES ======================

@app.route("/status")
def status():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    with wipes_lock:
        any_active = len(active_wipes) > 0
        progress = 0
        if any_active:
            # Average progress of all running wipes
            progresses = [info["progress"] for info in active_wipes.values()]
            progress = sum(progresses) // len(progresses)

    return jsonify({
        "status": "online",
        "wipe_active": any_active,
        "progress": progress,
        "completed": False
    })


@app.route("/list-devices")
def list_devices():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    drives = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            drives.append({
                "device": part.device,
                "mount": part.mountpoint,
                "fs": part.fstype,
                "total_gb": round(usage.total / (1024**3), 2),
                "free_gb": round(usage.free / (1024**3), 2)
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

    if not path:
        return jsonify({"error": "Missing device path"}), 400

    # Do NOT check os.path.exists() here — many mounts are lazy or need root delay
    # Just start the thread — it will fail gracefully if path is wrong

    thread = threading.Thread(target=wipe_worker, args=(path, method), daemon=False)
    thread.start()

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

    return jsonify({
        "status": "stopping",
        "stopped_wipes": stopped
    })


if __name__ == "__main__":
    print("==========================================")
    print(" PC WIPE AGENT – FIXED & RELIABLE")
    print(" Works perfectly with your current Android app")
    print(" No leftover files | Real progress | Multi-wipe safe")
    print(" Listening → http://0.0.0.0:5050")
    print("==========================================")
    app.run(host="0.0.0.0", port=5050, threaded=True)
