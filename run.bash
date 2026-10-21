#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

machine="podman-machine-default"

docker build --target notebook -t movie-actor-notebook .

docker run --rm \
  -v "$PWD:/app" \
  movie-actor-notebook \
  python check_environment.py
