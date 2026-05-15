#!/usr/bin/env bash
# lean_watchdog_a7_kochen_specker.sh — Lean swarm watchdog for a7_kochen_specker.
# Delegates to scripts/watchdog_common.sh.

REPO=/root/gaia-discovery
export PROJ="/personal/lean_swarm/projects/a7_kochen_specker"
export LAUNCHER="$REPO/scripts/launch_lean_a7_kochen_specker.sh"
export LOG="/personal/lean_swarm/logs/a7_kochen_specker.watchdog.log"
export STDOUT_LOG="/personal/lean_swarm/logs/a7_kochen_specker.stdout.log"

exec bash "$REPO/scripts/watchdog_common.sh"
