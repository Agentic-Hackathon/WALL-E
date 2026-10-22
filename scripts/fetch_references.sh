#!/usr/bin/env bash
# دانلود shallow منابع خارجی فقط برای مطالعه؛ بدون اجرا و بدون استفاده از کلید والکس.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p third_party
OUT=third_party/SOURCES.md

record_unavailable() { # record_unavailable <url>
  local url="$1"
  if ! grep -Fq "| $url |" "$OUT"; then
    echo "| $url | — | unavailable (clone failed) | no code used |" >> "$OUT"
  fi
}

record_pending_license() { # record_pending_license <url> <sha>
  local url="$1" sha="$2"
  if ! grep -Fq "| $url |" "$OUT"; then
    echo "| $url | \`$sha\` | pending: read LICENSE | study only; no code copied |" >> "$OUT"
  fi
}

clone() { # clone <name> <url>
  local name="$1" url="$2" dir="third_party/$name"
  if [ ! -d "$dir/.git" ]; then
    if ! git clone --depth 1 "$url" "$dir"; then
      record_unavailable "$url"
      echo "[unavailable] $name: recorded in $OUT; continuing." >&2
      return 0
    fi
  fi
  local sha
  sha=$(git -C "$dir" rev-parse HEAD)
  record_pending_license "$url" "$sha"
  echo "[ok] $name @ $sha"
  echo "Read the repository LICENSE before copying any code; record its commit and licence in $OUT."
}

clone hindsight        https://github.com/Ajay03299/hindsight
clone trading-bot      https://github.com/yashdhingra0/trading-bot
clone grid_trading_bot https://github.com/jordantete/grid_trading_bot
clone FinMem           https://github.com/pipiku915/FinMem-LLM-StockTrading
clone TradingAgents    https://github.com/TauricResearch/TradingAgents
clone lumibot          https://github.com/Lumiwealth/lumibot
clone FinRL-Trading    https://github.com/AI4Finance-Foundation/FinRL-Trading
