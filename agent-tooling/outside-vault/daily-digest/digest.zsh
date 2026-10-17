#!/bin/zsh
# 朝のダイジェスト / 月初のお金チェックを codex exec で作り、Discord（自分のサーバーの #digest）に送る。launchd から呼ぶ。
#   digest.zsh morning|money [--dry-run]
# 設定: ~/.config/notify/daily-digest.env（chmod 600）
#   WEBHOOK_URL=...         #digest の Webhook「digest」
#   HC_URL_MORNING=...      Healthchecks.io のチェック morning-digest の ping URL
#   HC_URL_MONEY=...        同 money-check
# 設定が無い、または --dry-run のときは標準出力に出すだけ。
set -uo pipefail
DIR=${0:A:h}
KIND=${1:?morning か money を指定}
DRY=${2:-}
VAULT=${VAULT:-$HOME/Desktop/Obsidian}
CONF=${DIGEST_CONF:-$HOME/.config/notify/daily-digest.env}
[[ -f $CONF ]] && source $CONF
WEBHOOK_URL=${WEBHOOK_URL:-}
HC_VAR="HC_URL_${(U)KIND}"; HC=${(P)HC_VAR:-}
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
# launchd の既定の上限（同時に開けるファイル数 256）だと codex exec が
# "low max file descriptors" で落ちる（2026-10-03 の朝に発生）。天井は無制限なので引き上げる
ulimit -n 10240 2>/dev/null || ulimit -n 4096 2>/dev/null

ping() { [[ -n $HC && -z $DRY ]] && curl -fsS -m 10 --retry 3 --data-raw "${2:-}" "$HC$1" >/dev/null; return 0; }

# 読み取り制約と最終応答の抽出は codex_digest.py で行う。
# 定期実行のモデルを対話セッションの既定から独立させる。
DIGEST_MODEL=gpt-6.1-sol
case $KIND in
  morning) DIGEST_EFFORT=medium ;;
  money) DIGEST_EFFORT=high ;;
  *) print -u2 -- "Usage: digest.zsh morning|money [--dry-run]"; exit 2 ;;
esac

ping /start
cd $VAULT
digest_started=$SECONDS
out=$(python3 "$DIR/codex_digest.py" "$KIND" "$VAULT" "$DIR/$KIND.md")
rc=$?
# 本文を含めず、実行設定・成否・経過秒だけを既存のlaunchdログへ出す。
print -u2 -- "digest: kind=$KIND model=$DIGEST_MODEL effort=$DIGEST_EFFORT rc=$rc elapsed=$((SECONDS - digest_started))s"
if (( rc != 0 )) || [[ -z $out ]]; then
  ping /fail "codex exec failed rc=$rc"
  print -r -- "$out" >&2
  exit 1
fi

# 「集め終わりました」などの前置きが付くことがあるので、見出し（**🌅 / **💴）より前は捨てる
marker=$([[ $KIND == morning ]] && print '**🌅' || print '**💴')
[[ $out == *"$marker"* ]] && out="$marker${out#*$marker}"

if [[ -n $DRY || -z $WEBHOOK_URL ]]; then
  print -r -- "$out"
else
  print -rn -- "$out" | python3 -c 'import json,sys; print(json.dumps({"content": sys.stdin.read()[:1990], "username": "digest"}))' \
    | curl -fsS -m 15 -H "Content-Type: application/json" -d @- "$WEBHOOK_URL" >/dev/null \
    || { ping /fail "discord post failed"; exit 1; }
fi
ping "" "${#out} chars"
