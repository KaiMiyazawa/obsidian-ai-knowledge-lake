#!/bin/zsh

# Local desktop-authenticated audit. Never print password values.
set -euo pipefail

readonly OP_BIN="/usr/local/bin/op"
readonly VAULT="${1:-AI-Managed}"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

OP_BIOMETRIC_UNLOCK_ENABLED=true "$OP_BIN" item list --vault "$VAULT" --format json > "$tmpdir/items.json"
print -r -- "id\ttitle\tlength\treasons"
jq -r '.[] | [.id, .title] | @tsv' "$tmpdir/items.json" | while IFS=$'\t' read -r id title; do
  item_json="$tmpdir/item.json"
  OP_BIOMETRIC_UNLOCK_ENABLED=true "$OP_BIN" item get "$id" --vault "$VAULT" --format json > "$item_json"
  password="$(jq -r '[.fields[]? | select(.label == "password" or .id == "password") | .value][0] // ""' "$item_json")"
  [[ -n "$password" ]] || continue

  reasons=()
  (( ${#password} < 12 )) && reasons+=("short")
  [[ "$password" != *[A-Z]* ]] && reasons+=("no-upper")
  [[ "$password" != *[a-z]* ]] && reasons+=("no-lower")
  [[ "$password" != *[0-9]* ]] && reasons+=("no-digit")
  [[ "$password" != *['!@#$%^\\&*()_+\-=\[\]{}:;\"\\\|,.<>/?']* ]] && reasons+=("no-symbol")
  (( ${#reasons[@]} > 0 )) && print -r -- "$id\t$title\t${#password}\t${(j:,:)reasons}"
done
