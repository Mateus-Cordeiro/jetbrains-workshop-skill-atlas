#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
mkdir -p test-results/visual tests/browser/visual/snapshots
image=skill-atlas-visual:local
docker build --platform linux/amd64 -f tests/browser/visual/Dockerfile -t "$image" .
# Dependencies are installed at build time. Test execution has no external network.
docker run --rm --platform linux/amd64 --network none --shm-size=1g \
  -e CI="${CI:-}" -e ATLAS_DEMO="${ATLAS_DEMO:-0}" \
  -v "$PWD/test-results/visual:/work/test-results/visual" \
  -v "$PWD/tests/browser/visual/snapshots:/work/tests/browser/visual/snapshots" \
  "$image" npm run test:visual -- "$@"
