#!/bin/bash
# Run db-meta-v2 MCP server

set -e

cd "$(dirname "$0")"

# Ensure dependencies are installed
uv sync

# Run the server
uv run python -m db_meta_v2
