#!/usr/bin/env bash
# lean_watchdog_a4_squashed_monogamy.sh — Lean swarm watchdog for a4_squashed_monogamy.
# Delegates to scripts/watchdog_common.sh.

REPO=/root/gaia-discovery
export PROJ="/personal/lean_swarm/projects/a4_squashed_monogamy"
export LAUNCHER="$REPO/scripts/launch_lean_a4_squashed_monogamy.sh"
export LOG="/personal/lean_swarm/logs/a4_squashed_monogamy.watchdog.log"
export STDOUT_LOG="/personal/lean_swarm/logs/a4_squashed_monogamy.stdout.log"

export LEAN_VERIFY_BUILD="PhysicsLean.A4SquashedMonogamy.Theorem"
export LEAN_VERIFY_ROOT="/personal/lean_swarm/lean"
exec bash "$REPO/scripts/watchdog_common.sh"
