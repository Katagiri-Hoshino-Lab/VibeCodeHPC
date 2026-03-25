#!/bin/bash
# Minimal wrapper for VibeCodeHPC agent messaging
# Usage: ./agent_send.sh PM "message"
exec python3 -m vibecodehpc send "$@"
