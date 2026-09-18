---
name: lab-status
description: >
  Report the current health of this shared lab compute server: disk
  space per filesystem, memory and load, and which users/processes
  are consuming CPU and RAM right now. Use this whenever the user
  asks to check the server, see who's running what, check disk
  space, see if the machine is overloaded or slow, or wants a
  general "how's the machine doing" / "is it safe to start a big
  job" overview. Also use it if they ask what's eating disk space in
  a specific directory, or who is hogging CPU/memory. This is a
  shared multi-user machine, so always frame findings by user, not
  just by process.
---

# Lab server status

This machine is shared by multiple lab members for compute-heavy
jobs (phylogenetics, sequence alignment, R/targets pipelines, etc).
The goal of this skill is a fast, honest snapshot of machine health
-- not a full monitoring dashboard.

## Step 1: run the collector

```
scripts/report.sh
```

This gathers everything in well under a second: filesystem usage,
memory/load, per-user CPU+memory aggregates, top processes by CPU
and by memory, and GPU status if `nvidia-smi` works. It only prints
raw data with section headers -- your job is to interpret it, not
just relay it.

Note what it deliberately does *not* do: it does not `du` through
home directories to attribute disk usage per user. On this host,
home directories are typically mode `750` with per-user groups, so
a non-root user can only ever see their own tree -- a system-wide
per-user disk report would be silently wrong for everyone else. If
someone wants that, see Step 3.

## Step 2: write the report

Structure your answer like this:

1. **Flags first.** One short bullet list of anything that actually
   needs attention, or "Nothing urgent" if there isn't. Use these
   thresholds as a starting point, not hard rules -- use judgment
   about what's actually worth surfacing on a compute box like this:
   - A filesystem at or above ~85% used (90%+ is more urgent).
   - Load average (1-min) well above the CPU core count, e.g. more
     than ~1.5x -- indicates the box is oversubscribed right now.
   - Swap in active use (a little is often fine; watch the trend,
     not just the number).
   - Any single user consuming a very large share of CPU or memory
     relative to everyone else, in case it's a runaway/stuck job
     rather than intentional work.
2. **Disk space** -- table or short list per mounted filesystem:
   size, used, available, use%. Call out the one(s) that are tight.
3. **CPU & memory** -- lead with the per-user aggregate table (who's
   using the machine right now, and how much), then list the
   top few individual processes by CPU and by memory so the user can
   tell *what* those jobs actually are (job names, not just PIDs).
   Long-running high-CPU processes (check `etime`) are normal here
   (multi-day phylogenetics runs, etc) -- don't flag a job as a
   problem just for being long-running or using many cores; flag it
   only if it looks stuck, duplicated by accident, or is crowding
   out other users.
4. **GPU** -- only include this section if a GPU was actually
   detected; omit it entirely on a CPU-only box rather than saying
   "no GPU" every time.

Keep the whole thing scannable -- this is meant to be read in a few
seconds, not studied.

## Step 3: disk space deep-dive (only if asked)

If the user (or the flags in step 1) point at a specific directory
they want to investigate -- e.g. "what's filling up my home dir" --
use the second script instead of trying to `du` it yourself:

```
scripts/dig.sh [path] [depth] [timeout_seconds]
```

Defaults: `path=$HOME`, `depth=1`, `timeout=60`. It stays on one
filesystem (`du -x`) so it doesn't wander into NFS/bind mounts and
take forever, and it tells you plainly if it timed out (tree is
genuinely huge -- try a longer budget or narrower path) versus hit
permission errors partway through (some subdirectories aren't
readable by this user).

Don't try to run a system-wide per-user disk audit this way -- it
will hang or silently under-report for every user whose directories
this account can't read. If the user specifically needs that, tell
them it requires root (e.g. `sudo du -sh /home/*`) and that you
won't run `sudo` yourself since it needs an interactive password and
is a privileged action -- they should run it themselves if wanted.
