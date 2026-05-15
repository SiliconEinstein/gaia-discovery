#!/usr/bin/env bash
# lean_watchdog_a5_nocloning.sh — Lean swarm watchdog for a5_nocloning.
# Delegates to scripts/watchdog_common.sh.

REPO=/root/gaia-discovery
export PROJ="/personal/lean_swarm/projects/a5_nocloning"
export LAUNCHER="$REPO/scripts/launch_lean_a5_nocloning.sh"
export LOG="/personal/lean_swarm/logs/a5_nocloning.watchdog.log"
export STDOUT_LOG="/personal/lean_swarm/logs/a5_nocloning.stdout.log"

exec bash "$REPO/scripts/watchdog_common.sh"
