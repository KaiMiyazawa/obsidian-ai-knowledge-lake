#!/bin/zsh

# Run 1Password CLI through the AI-Managed Service Account without storing
# the Service Account token in this vault, Git, or the chat.
set -euo pipefail

readonly OP_BIN="/usr/local/bin/op"
readonly PERSONAL_VAULT_ID="<PERSONAL_VAULT_ID>"
readonly TOKEN_ITEM_ID="<TOKEN_ITEM_ID>"

token="$({ OP_BIOMETRIC_UNLOCK_ENABLED=true "$OP_BIN" item get "$TOKEN_ITEM_ID" \
  --vault "$PERSONAL_VAULT_ID" \
  --fields label=credential --reveal --format json; } | jq -r '.value')"

[[ -n "$token" && "$token" != "null" ]]
exec env OP_SERVICE_ACCOUNT_TOKEN="$token" "$OP_BIN" "$@"
