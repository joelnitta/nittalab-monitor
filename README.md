# nittalab-monitor

Lightweight monitoring for a shared lab compute server: disk space,
and CPU/memory usage for whoever's running jobs right now. Built for
a multi-user Linux box used for compute-heavy work (phylogenetics,
sequence alignment, R pipelines, etc.), where "is it safe to start a
big job" and "who's using all the RAM" are the recurring questions.

No external dependencies -- everything here shells out to standard
tools (`df`, `free`, `ps`, `nvidia-smi` if present) or uses the
Python standard library.

## What's in here

- **[`.claude/skills/lab-status/`](.claude/skills/lab-status/)** --
  a [Claude Code](https://claude.com/claude-code) skill that
  generates an on-demand health report: flags anything worth
  attention (disk pressure, an oversubscribed load average, a
  runaway job), then breaks down disk usage per filesystem and
  CPU/memory per user and per process. Also includes a scoped
  disk-space deep-dive tool for hunting down what's filling up a
  specific directory.

- **[`webapp/`](webapp/README.md)** -- the same data as a small,
  live, auto-refreshing browser dashboard, meant to be left running
  continuously (as a systemd user service) rather than run on
  demand. See its README for setup, including how to view it
  painlessly through VS Code's Remote-SSH port forwarding.

## Why two versions of the same data

The skill is for asking a question and getting an interpreted
answer ("is anything wrong?", "what's eating my disk space?"). The
dashboard is for glancing at a browser tab to see the current state
without asking anything. Both scripts read the same underlying
system commands, so they won't drift out of sync in what they
consider "normal."

## A note on permissions

This machine's home directories are typically mode `750` with
per-user groups, so a non-root user can only ever see their own
files -- there's no reliable way to compute total disk usage broken
down by user without root. Both the skill and the dashboard lean on
`df` (filesystem-level, always accurate) for the disk-space signal
that actually matters, rather than trying to fake a per-user
breakdown that would silently be wrong for accounts other than your
own.

## License

[MIT](LICENSE)
