#!/usr/bin/env bash
# lean_watchdog_b9_solovay_kitaev.sh — Lean swarm watchdog for b9_solovay_kitaev.
# Delegates to scripts/watchdog_common.sh.

REPO=/root/gaia-discovery
export PROJ="/personal/lean_swarm/projects/b9_solovay_kitaev"
export LAUNCHER="$REPO/scripts/launch_lean_b9_solovay_kitaev.sh"
export LOG="/personal/lean_swarm/logs/b9_solovay_kitaev.watchdog.log"
export STDOUT_LOG="/personal/lean_swarm/logs/b9_solovay_kitaev.stdout.log"

export LEAN_VERIFY_BUILD="PhysicsLean.B9SolovayKitaev.Theorem"
export LEAN_VERIFY_ROOT="/personal/lean_swarm/lean"
exec bash "$REPO/scripts/watchdog_common.sh"
