#!/usr/bin/env bash

# Get the directory of the script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Check if port 8000 is already in use
if lsof -i :8000 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Error: Port 8000 is already in use. Maybe the server is already running?"
    exit 1
fi

echo "Starting web-scraper MCP server in the background..."
nohup uv run web-scraper-mcp > server.log 2>&1 &
PID=$!

echo "Server started with PID: $PID"
echo "Logs are being written to: $DIR/server.log"
echo "To stop the server, run: kill $PID  or  kill \$(lsof -t -i:8000)"
