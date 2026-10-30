#!/usr/bin/env bash
# Build command for Vercel's Git deployments (project root directory: website/).
# The API reference is generated from the Python sources, so the build needs uv.
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  python3 -m pip install --quiet --user uv==0.12.15
  export PATH="$(python3 -m site --user-base)/bin:$PATH"
fi

npm run generate:api
npm run build
