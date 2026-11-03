#!/bin/bash
# Keep the wellness card API up: restart it if it ever exits.
# Run inside tmux: tmux new-session -d -s wellness "bash scripts/run.sh"
env_file="$HOME/.config/wellness-survey/env"
if [[ ! -r "$env_file" ]]; then
  echo "$(date '+%F %T') missing $env_file, not starting" >> "$HOME/Library/Logs/wellness-survey.log"
  exit 1
fi
set -a; . "$env_file"; set +a
cd "$(dirname "$0")/.."
log="$HOME/Library/Logs/wellness-survey.log"
while true; do
  /opt/homebrew/bin/python3 server/wellness_server.py >> "$log" 2>&1
  echo "$(date '+%F %T') server exited, restarting" >> "$log"
  sleep 2
done
