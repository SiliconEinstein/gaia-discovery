#!/usr/bin/env bash
# ppt2_watchdog.sh — A-line PPT² main agent watchdog.
# Delegates all logic to scripts/watchdog_common.sh; only project-specific env here.
#
# Stop with: pkill -f 'ppt2_watchdog.sh'

REPO=/root/gaia-discovery
export PROJ="$REPO/projects/ppt2_main"
export LAUNCHER="$REPO/scripts/launch_ppt2_main.sh"
export LOG="$REPO/logs/ppt2_main.watchdog.log"
export STDOUT_LOG="$REPO/logs/ppt2_main.stdout.log"

exec bash "$REPO/scripts/watchdog_common.sh"
