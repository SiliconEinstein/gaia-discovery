#!/usr/bin/env bash
# lean_watchdog_a10_tsirelson.sh — Lean swarm watchdog for a10_tsirelson.
# Delegates to scripts/watchdog_common.sh.

REPO=/root/gaia-discovery
export PROJ="/personal/lean_swarm/projects/a10_tsirelson"
export LAUNCHER="$REPO/scripts/launch_lean_a10_tsirelson.sh"
export LOG="/personal/lean_swarm/logs/a10_tsirelson.watchdog.log"
export STDOUT_LOG="/personal/lean_swarm/logs/a10_tsirelson.stdout.log"

exec bash "$REPO/scripts/watchdog_common.sh"
