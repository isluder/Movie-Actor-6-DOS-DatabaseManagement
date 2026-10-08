#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

machine="podman-machine-default"

docker build -t movie-actor-python .

docker run --rm \
  -v "$PWD:/app" \
  movie-actor-python \
  python check_environment.py
