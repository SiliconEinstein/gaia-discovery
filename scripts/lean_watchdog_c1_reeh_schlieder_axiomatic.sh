#!/usr/bin/env bash
# lean_watchdog_c1_reeh_schlieder_axiomatic.sh — Lean swarm watchdog for c1_reeh_schlieder_axiomatic.
# Delegates to scripts/watchdog_common.sh.

REPO=/root/gaia-discovery
export PROJ="/personal/lean_swarm/projects/c1_reeh_schlieder_axiomatic"
export LAUNCHER="$REPO/scripts/launch_lean_c1_reeh_schlieder_axiomatic.sh"
export LOG="/personal/lean_swarm/logs/c1_reeh_schlieder_axiomatic.watchdog.log"
export STDOUT_LOG="/personal/lean_swarm/logs/c1_reeh_schlieder_axiomatic.stdout.log"

export LEAN_VERIFY_BUILD="PhysicsLean.C1ReehSchliederAxiomatic.Theorem"
export LEAN_VERIFY_ROOT="/personal/lean_swarm/lean"
exec bash "$REPO/scripts/watchdog_common.sh"
