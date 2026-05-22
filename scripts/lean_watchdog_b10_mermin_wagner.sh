#!/usr/bin/env bash
# lean_watchdog_b10_mermin_wagner.sh — Lean swarm watchdog for b10_mermin_wagner.
# Delegates to scripts/watchdog_common.sh.

REPO=/root/gaia-discovery
export PROJ="/personal/lean_swarm/projects/b10_mermin_wagner"
export LAUNCHER="$REPO/scripts/launch_lean_b10_mermin_wagner.sh"
export LOG="/personal/lean_swarm/logs/b10_mermin_wagner.watchdog.log"
export STDOUT_LOG="/personal/lean_swarm/logs/b10_mermin_wagner.stdout.log"

export LEAN_VERIFY_BUILD="PhysicsLean.B10MerminWagner.Theorem"
export LEAN_VERIFY_ROOT="/personal/lean_swarm/lean"
exec bash "$REPO/scripts/watchdog_common.sh"
