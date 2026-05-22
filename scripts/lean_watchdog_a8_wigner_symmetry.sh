#!/usr/bin/env bash
# lean_watchdog_a8_wigner_symmetry.sh — Lean swarm watchdog for a8_wigner_symmetry.
# Delegates to scripts/watchdog_common.sh.

REPO=/root/gaia-discovery
export PROJ="/personal/lean_swarm/projects/a8_wigner_symmetry"
export LAUNCHER="$REPO/scripts/launch_lean_a8_wigner_symmetry.sh"
export LOG="/personal/lean_swarm/logs/a8_wigner_symmetry.watchdog.log"
export STDOUT_LOG="/personal/lean_swarm/logs/a8_wigner_symmetry.stdout.log"

export LEAN_VERIFY_BUILD="PhysicsLean.A8WignerSymmetry.Theorem"
export LEAN_VERIFY_ROOT="/personal/lean_swarm/lean"
exec bash "$REPO/scripts/watchdog_common.sh"
