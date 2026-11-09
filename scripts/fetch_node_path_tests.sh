#!/bin/sh
# Fetches Node's own path tests for the running Node version into
# tests/oracle/node_path/test/parallel, the input of tests/oracle/node_path/oracle.cjs.
set -eu
version="v$(node -p process.versions.node)"
dir="$(dirname "$0")/../tests/oracle/node_path/test/parallel"
mkdir -p "$dir"
for name in $(gh api "repos/nodejs/node/git/trees/$version:test/parallel" --jq '.tree[].path' |
  grep '^test-path.*\.js$' | grep -v '^test-path-glob\.js$'); do
  gh api "repos/nodejs/node/contents/test/parallel/$name?ref=$version" \
    -H "Accept: application/vnd.github.raw" > "$dir/$name"
done
