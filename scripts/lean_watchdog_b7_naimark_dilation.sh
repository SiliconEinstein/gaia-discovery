#!/usr/bin/env bash
# lean_watchdog_b7_naimark_dilation.sh — Lean swarm watchdog for b7_naimark_dilation.
# Delegates to scripts/watchdog_common.sh.

REPO=/root/gaia-discovery
export PROJ="/personal/lean_swarm/projects/b7_naimark_dilation"
export LAUNCHER="$REPO/scripts/launch_lean_b7_naimark_dilation.sh"
export LOG="/personal/lean_swarm/logs/b7_naimark_dilation.watchdog.log"
export STDOUT_LOG="/personal/lean_swarm/logs/b7_naimark_dilation.stdout.log"

exec bash "$REPO/scripts/watchdog_common.sh"
