#!/usr/bin/env bash
# Collects raw system-health data for the lab-status skill.
# Deliberately dumps plain data with section markers -- Claude
# interprets and formats it, this script just gathers it reliably.
set -uo pipefail

section() { printf '\n=== %s ===\n' "$1"; }

section "Host"
hostname
uptime -p 2>/dev/null || uptime
echo "CPUs: $(nproc)"

section "Load average & memory"
cat /proc/loadavg
free -h

section "Disk usage (mounted filesystems)"
df -hT -x tmpfs -x devtmpfs -x squashfs -x overlay 2>/dev/null

section "CPU/memory usage by user (aggregated across processes)"
{
  printf '%-12s %6s %8s %8s\n' "USER" "PROCS" "CPU%" "MEM%"
  ps -eo user,pcpu,pmem --no-headers | awk '
    { cpu[$1]+=$2; mem[$1]+=$3; n[$1]++ }
    END { for (u in cpu) printf "%s\t%d\t%.1f\t%.1f\n", u, n[u], cpu[u], mem[u] }
  ' | sort -t$'\t' -k3 -rn | awk -F'\t' \
    '{ printf "%-12s %6d %8.1f %8.1f\n", $1, $2, $3, $4 }'
}

section "Top processes by CPU"
ps -eo user,pid,pcpu,pmem,etime,cmd --sort=-pcpu --no-headers | head -15

section "Top processes by memory"
ps -eo user,pid,pcpu,pmem,etime,cmd --sort=-pmem --no-headers | head -15

section "GPU status (if available)"
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu \
    --format=csv
else
  echo "No GPU detected / nvidia-smi not available"
fi
