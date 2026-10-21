#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

docker build --target runtime -t movie-actor-python .
docker run --rm \
  -p 127.0.0.1:5000:5000 \
  -v "$PWD:/app" \
  movie-actor-python \
  python -m flask --app src.app:create_app run --host 0.0.0.0 --port 5000
