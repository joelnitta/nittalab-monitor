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
ssh -L 8799:localhost:8799 jnitta@rx2000
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
put the same block in your **Remote [SSH: nittalab]** settings
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
