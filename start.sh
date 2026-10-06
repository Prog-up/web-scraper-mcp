#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
# Foreground execution: configuration/startup errors reach the caller and signals
# go directly to the server. Use systemd or Docker restart policies for supervision.
exec uv run --frozen web-scraper-mcp
