Place Qdrant snapshot files in this directory before starting the Docker Compose stack.

The `qdrant-init` service mounts this folder at `/snapshots` and runs `restore.py` against the `qdrant` service once it is healthy.
