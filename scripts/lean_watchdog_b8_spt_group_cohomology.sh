#!/usr/bin/env bash
# lean_watchdog_b8_spt_group_cohomology.sh — Lean swarm watchdog for b8_spt_group_cohomology.
# Delegates to scripts/watchdog_common.sh.

REPO=/root/gaia-discovery
export PROJ="/personal/lean_swarm/projects/b8_spt_group_cohomology"
export LAUNCHER="$REPO/scripts/launch_lean_b8_spt_group_cohomology.sh"
export LOG="/personal/lean_swarm/logs/b8_spt_group_cohomology.watchdog.log"
export STDOUT_LOG="/personal/lean_swarm/logs/b8_spt_group_cohomology.stdout.log"

export LEAN_VERIFY_BUILD="PhysicsLean.B8SptGroupCohomology.Theorem"
export LEAN_VERIFY_ROOT="/personal/lean_swarm/lean"
exec bash "$REPO/scripts/watchdog_common.sh"
