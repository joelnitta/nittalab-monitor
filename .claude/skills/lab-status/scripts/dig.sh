#!/usr/bin/env bash
# On-demand disk-space deep dive for one directory the caller can
# actually read. Not run by default in report.sh: du over a whole
# home tree is slow and, on this host, home dirs are mode 750 with
# per-user groups, so this can only ever see paths the invoking user
# has permission to read (their own home, or shared/group dirs).
#
# Usage: dig.sh [path] [depth] [timeout_seconds]
set -uo pipefail

path="${1:-$HOME}"
depth="${2:-1}"
budget="${3:-60}"

if [ ! -r "$path" ]; then
  echo "Cannot read '$path' -- check the path and permissions." >&2
  exit 1
fi

echo "Largest entries under $path (depth=$depth, budget=${budget}s)"
echo "-x: stays on one filesystem, won't wander into NFS/bind mounts"
echo

# timeout's exit code distinguishes a real timeout (124) from du
# hitting permission errors partway through (1) -- worth telling
# these apart since they call for different next steps.
timeout "$budget" du -x -h --max-depth="$depth" "$path" 2>/tmp/dig-du-err.$$ \
  | sort -rh
status=$?

if [ -s /tmp/dig-du-err.$$ ]; then
  echo
  echo "Some entries were skipped (permission denied):"
  grep -o "cannot read directory '[^']*'" /tmp/dig-du-err.$$ | sort -u
fi
rm -f /tmp/dig-du-err.$$

if [ "$status" -eq 124 ]; then
  echo
  echo "Timed out after ${budget}s -- this tree is big. Try a larger" \
       "timeout, a smaller depth, or narrow to a subdirectory."
fi
