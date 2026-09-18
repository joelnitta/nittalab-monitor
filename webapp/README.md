# Live status dashboard

A small, dependency-free (stdlib-only) web dashboard for the same
data the `lab-status` skill reports: disk usage, load/memory, and
CPU/memory by user and process. It polls itself every 5 seconds.

It binds to `127.0.0.1` only. Other users' process command lines
(file paths, job arguments) are visible on this dashboard, so it's
kept off the network by design -- reach it via an SSH tunnel or by
browsing on the machine itself.

## Run it once, ad hoc

```
python3 webapp/status_server.py
```

Then open <http://localhost:8799/>. From your laptop, tunnel first:

```
ssh -L 8799:localhost:8799 jnitta@rx2000
```

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
