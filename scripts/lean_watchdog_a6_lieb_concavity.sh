#!/usr/bin/env bash
# lean_watchdog_a6_lieb_concavity.sh — Lean swarm watchdog for a6_lieb_concavity.
# Delegates to scripts/watchdog_common.sh.

REPO=/root/gaia-discovery
export PROJ="/personal/lean_swarm/projects/a6_lieb_concavity"
export LAUNCHER="$REPO/scripts/launch_lean_a6_lieb_concavity.sh"
export LOG="/personal/lean_swarm/logs/a6_lieb_concavity.watchdog.log"
export STDOUT_LOG="/personal/lean_swarm/logs/a6_lieb_concavity.stdout.log"

exec bash "$REPO/scripts/watchdog_common.sh"
