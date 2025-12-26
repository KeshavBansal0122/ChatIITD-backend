import os
import time
import requests
import sys

# Configuration
QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = os.environ.get("QDRANT_PORT", "6333")
QDRANT_URL = f"http://{QDRANT_HOST}:{QDRANT_PORT}"
SNAPSHOTS_DIR = "/snapshots"

def wait_for_qdrant():
    print(f"Waiting for Qdrant at {QDRANT_URL}...")
    for _ in range(60): # Wait up to 120 seconds
        try:
            response = requests.get(f"{QDRANT_URL}/healthz")
            if response.status_code == 200:
                print("Qdrant is ready.")
                return
        except Exception as e:
            print(f"Waiting... ({e})")
        time.sleep(2)
    print("Qdrant did not become ready in time.")
    sys.exit(1)

def collection_exists(collection_name):
    try:
        response = requests.get(f"{QDRANT_URL}/collections/{collection_name}")
        return response.status_code == 200
    except Exception:
        return False

def restore_snapshot(collection_name, snapshot_file):
    if collection_exists(collection_name):
        print(f"Collection '{collection_name}' already exists. Skipping restore.")
        return

    file_path = os.path.join(SNAPSHOTS_DIR, snapshot_file)
    if not os.path.exists(file_path):
        print(f"Snapshot file {file_path} not found. Skipping.")
        return

    print(f"Restoring collection '{collection_name}' from {snapshot_file}...")
    
    # Upload the snapshot to restore the collection
    # The parameter 'priority=snapshot' ensures it creates the collection from snapshot
    try:
        with open(file_path, "rb") as f:
            files = {"snapshot": (snapshot_file, f)}
            response = requests.post(
                f"{QDRANT_URL}/collections/{collection_name}/snapshots/upload?priority=snapshot",
                files=files
            )
            if response.status_code == 200:
                print(f"Successfully restored '{collection_name}'.")
            else:
                print(f"Failed to restore '{collection_name}': {response.text}")
    except Exception as e:
        print(f"Error uploading snapshot: {e}")

if __name__ == "__main__":
    wait_for_qdrant()
    restore_snapshot("courses", "courses.snapshot")
    restore_snapshot("rules", "rules.snapshot")
