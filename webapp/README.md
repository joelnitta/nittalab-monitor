# Live status dashboard

A small, dependency-free (stdlib-only) web dashboard for the same
data the `lab-status` skill reports: disk usage, load/memory, and
CPU/memory by user and process. It polls itself every 5 seconds.

It binds to `127.0.0.1` only. Other users' process command lines
(file paths, job arguments) are visible on this dashboard, so it's
kept off the network by design -- reach it via an SSH tunnel or by
browsing on the machine itself. The service always listens on
**port 8799 on the remote host** -- that part never changes.

## Run it once, ad hoc

```
python3 webapp/status_server.py
```

Then, if you're on the machine directly, open
<http://localhost:8799/>. From your laptop, tunnel first:

```
ssh -L 8799:localhost:8799 <user>@<host>
```

## Access from VS Code Remote-SSH (no manual tunnel needed)

`.vscode/settings.json` in this repo sets `remote.SSH.defaultForwardedPorts`,
so opening this folder over Remote-SSH auto-forwards the dashboard --
no need to use the Ports panel. It maps remote port 8799 to
**local port 18799** (not 8799), specifically so it won't collide
with whatever ports your own local dev-server previews happen to be
using on your laptop. Bookmark <http://localhost:18799/>.

If you'd rather have it auto-forward *any* time you connect to this
host over Remote-SSH -- even without this specific folder open --
put the same block in your **Remote [SSH: &lt;host&gt;]** settings
(Command Palette -> "Preferences: Open Remote Settings (JSON)" while
connected) instead of relying on the workspace file:

```json
{
  "remote.SSH.defaultForwardedPorts": [
    { "name": "lab-status dashboard", "localPort": 18799, "remotePort": 8799 }
  ]
}
```

That's remote-machine-scoped (stored server-side, under your own
account), so it only ever fires when you personally connect to this
host -- it won't touch port forwarding on unrelated remotes or local
projects.

## Run it as an always-on background service

This uses a systemd **user** service, so it runs under your account
without needing root:

```
mkdir -p ~/.config/systemd/user
cp webapp/lab-status.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now lab-status.service
```

By default, user services stop when your last session ends. To keep
it running after you log out and across reboots:

```
loginctl enable-linger "$USER"
```

Useful commands:

```
systemctl --user status lab-status     # is it running?
journalctl --user -u lab-status -f     # tail its logs
systemctl --user restart lab-status    # after editing status_server.py
systemctl --user disable --now lab-status   # turn it off
```

## Email alerts

While the service is running, a background thread re-checks the
same disk/load/swap thresholds the dashboard shows as red flags
(every 60 seconds by default) and emails you when one goes critical
-- and again once it recovers. It re-alerts on a cooldown (default
60 minutes) rather than once per check, so a still-full disk doesn't
flood your inbox, but you also don't forget about it.

It's opt-in and off until configured:

```
cp webapp/alerts.env.example webapp/alerts.env
$EDITOR webapp/alerts.env   # set ALERT_EMAIL_TO=you@example.com
systemctl --user restart lab-status
```

`alerts.env` is gitignored -- it holds your real address and,
if you point it at an external provider, SMTP credentials. Never
commit it.

By default it sends through this host's local mail relay
(`localhost:25`), which needs no credentials at all -- confirmed
working on this machine. Whether it successfully reaches an
*external* inbox (Gmail, etc.) depends on this host's outbound mail
setup, which is outside this project's control. Verify it actually
arrives before relying on it:

```
python3 webapp/status_server.py --test-alert
```

This reads `ALERT_EMAIL_TO` from your environment (or `alerts.env`,
if you export it first) and sends one test email without starting
the server. If nothing arrives after a few minutes and your local
relay doesn't do outbound delivery, set `SMTP_HOST` / `SMTP_PORT` /
`SMTP_USER` / `SMTP_PASSWORD` / `SMTP_USE_TLS` in `alerts.env` to
point at an external SMTP provider instead (e.g. Gmail with an
[App Password](https://myaccount.google.com/apppasswords)).
