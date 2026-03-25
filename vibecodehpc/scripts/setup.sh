#!/bin/bash
# Minimal wrapper for VibeCodeHPC setup
# Usage: ./setup.sh --name PROJECT --workers 4 --cli claude
exec python3 -m vibecodehpc setup "$@"
