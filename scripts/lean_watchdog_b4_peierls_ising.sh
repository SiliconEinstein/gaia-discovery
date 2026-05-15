#!/usr/bin/env bash
# lean_watchdog_b4_peierls_ising.sh — Lean swarm watchdog for b4_peierls_ising.
# Delegates to scripts/watchdog_common.sh.

REPO=/root/gaia-discovery
export PROJ="/personal/lean_swarm/projects/b4_peierls_ising"
export LAUNCHER="$REPO/scripts/launch_lean_b4_peierls_ising.sh"
export LOG="/personal/lean_swarm/logs/b4_peierls_ising.watchdog.log"
export STDOUT_LOG="/personal/lean_swarm/logs/b4_peierls_ising.stdout.log"

exec bash "$REPO/scripts/watchdog_common.sh"
