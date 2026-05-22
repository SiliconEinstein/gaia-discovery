#!/usr/bin/env bash
# lean_watchdog_b6_fkg_inequality.sh — Lean swarm watchdog for b6_fkg_inequality.
# Delegates to scripts/watchdog_common.sh.

REPO=/root/gaia-discovery
export PROJ="/personal/lean_swarm/projects/b6_fkg_inequality"
export LAUNCHER="$REPO/scripts/launch_lean_b6_fkg_inequality.sh"
export LOG="/personal/lean_swarm/logs/b6_fkg_inequality.watchdog.log"
export STDOUT_LOG="/personal/lean_swarm/logs/b6_fkg_inequality.stdout.log"

export LEAN_VERIFY_BUILD="PhysicsLean.B6FkgInequality.Theorem"
export LEAN_VERIFY_ROOT="/personal/lean_swarm/lean"
exec bash "$REPO/scripts/watchdog_common.sh"
