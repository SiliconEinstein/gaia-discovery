#!/usr/bin/env bash
# lean_watchdog_a2_choi_theorem.sh — Lean swarm watchdog for a2_choi_theorem.
# Delegates to scripts/watchdog_common.sh.

REPO=/root/gaia-discovery
export PROJ="/personal/lean_swarm/projects/a2_choi_theorem"
export LAUNCHER="$REPO/scripts/launch_lean_a2_choi_theorem.sh"
export LOG="/personal/lean_swarm/logs/a2_choi_theorem.watchdog.log"
export STDOUT_LOG="/personal/lean_swarm/logs/a2_choi_theorem.stdout.log"

exec bash "$REPO/scripts/watchdog_common.sh"
