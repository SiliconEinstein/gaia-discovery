#!/usr/bin/env bash
# ppt2_p7_swarm_watchdog.sh — B-line PPT² P7 swarm watchdog.
# Delegates to scripts/watchdog_common.sh.
#
# Stop with: pkill -f 'ppt2_p7_swarm_watchdog.sh'

REPO=/root/gaia-discovery
export PROJ="$REPO/projects/ppt2_p7_swarm"
export LAUNCHER="$REPO/scripts/launch_ppt2_p7_swarm.sh"
export LOG="$REPO/logs/ppt2_p7_swarm.watchdog.log"
export STDOUT_LOG="$REPO/logs/ppt2_p7_swarm.stdout.log"

exec bash "$REPO/scripts/watchdog_common.sh"
