#!/usr/bin/env bash
# lean_watchdog_a9_2d_tqft_frobenius.sh — Lean swarm watchdog for a9_2d_tqft_frobenius.
# Delegates to scripts/watchdog_common.sh.

REPO=/root/gaia-discovery
export PROJ="/personal/lean_swarm/projects/a9_2d_tqft_frobenius"
export LAUNCHER="$REPO/scripts/launch_lean_a9_2d_tqft_frobenius.sh"
export LOG="/personal/lean_swarm/logs/a9_2d_tqft_frobenius.watchdog.log"
export STDOUT_LOG="/personal/lean_swarm/logs/a9_2d_tqft_frobenius.stdout.log"

exec bash "$REPO/scripts/watchdog_common.sh"
