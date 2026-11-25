#!/usr/bin/env bash
# Build command for Vercel's Git deployments (project root directory: website/).
# The API reference is generated from the Python sources, so the build needs uv.
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  python3 -m pip install --quiet --user uv==0.12.15
  export PATH="$(python3 -m site --user-base)/bin:$PATH"
fi

# The sitemap dates each guide by the last commit that changed it (app/sitemap.ts), and
# leaves the dates out in a shallow clone, which Vercel's is.
if [ "$(git rev-parse --is-shallow-repository 2>/dev/null)" = true ]; then
  GIT_TERMINAL_PROMPT=0 git fetch --unshallow --quiet ||
    echo "Could not fetch the git history: the sitemap leaves the guides undated."
fi

npm run generate:api
npm run build
