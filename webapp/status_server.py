#!/usr/bin/env python3
"""Local status dashboard for a shared lab compute server.

Stdlib-only (no pip installs needed) so it runs anywhere Python 3
does. Shells out to the same standard tools the lab-status skill
uses (df, free, ps, nvidia-smi) and serves the result as JSON plus a
static HTML/JS front end that polls it.

Binds to localhost only by default -- this exposes other users'
process command lines (file paths, job arguments), so don't widen
that without thinking about who else is on the network.
"""
from __future__ import annotations

import argparse
import email.message
import http.server
import json
import os
import shutil
import smtplib
import socket
import subprocess
import threading
import time
from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"

# Single source of truth for "is this bad" -- both the dashboard's
# flags and the email alerter read these, so a red meter and a
# missing/present email never disagree about what counts as critical.
THRESHOLDS = {
    "disk_warn_pct": 85,
    "disk_crit_pct": 90,
    "load_warn_ratio": 1.3,  # x the core count
    "load_crit_ratio": 2.0,
    "swap_warn_pct": 50,
    "swap_crit_pct": 85,
}


def severity(value: float, warn_at: float, crit_at: float) -> str:
    if value >= crit_at:
        return "critical"
    if value >= warn_at:
        return "warning"
    return "ok"


def human_bytes(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"


def run(cmd: list[str]) -> str:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=5
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def get_disks() -> list[dict]:
    out = run(
        [
            "df", "-T", "--block-size=1",
            "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs", "-x", "overlay",
        ]
    )
    disks = []
    for line in out.splitlines()[1:]:
        parts = line.split(maxsplit=6)
        if len(parts) < 7:
            continue
        fs, fstype, size, used, avail, use_pct, mount = parts
        try:
            size_b, used_b, avail_b = int(size), int(used), int(avail)
        except ValueError:
            continue
        pct = int(use_pct.rstrip("%") or 0)
        disks.append(
            {
                "filesystem": fs,
                "type": fstype,
                "mount": mount,
                "size_bytes": size_b,
                "used_bytes": used_b,
                "avail_bytes": avail_b,
                "use_pct": pct,
                "severity": severity(
                    pct, THRESHOLDS["disk_warn_pct"], THRESHOLDS["disk_crit_pct"]
                ),
            }
        )
    return disks


def get_load_and_memory() -> dict:
    loadavg = run(["cat", "/proc/loadavg"]).split()
    load1, load5, load15 = (
        (float(loadavg[i]) for i in range(3)) if len(loadavg) >= 3 else (0, 0, 0)
    )
    ncpu = os.cpu_count() or 1

    mem = {}
    for line in run(["free", "-b"]).splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0].startswith("Mem:"):
            mem["total"], mem["used"], mem["free"] = map(int, fields[1:4])
            if len(fields) >= 7:
                mem["available"] = int(fields[6])
        elif fields[0].startswith("Swap:"):
            mem["swap_total"], mem["swap_used"], mem["swap_free"] = map(
                int, fields[1:4]
            )
    return {
        "load1": load1,
        "load5": load5,
        "load15": load15,
        "ncpu": ncpu,
        "memory": mem,
    }


def get_users() -> list[dict]:
    out = run(["ps", "-eo", "user,pcpu,pmem", "--no-headers"])
    agg: dict[str, dict] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        user, cpu, mem = parts
        row = agg.setdefault(user, {"user": user, "procs": 0, "cpu": 0.0, "mem": 0.0})
        row["procs"] += 1
        try:
            row["cpu"] += float(cpu)
            row["mem"] += float(mem)
        except ValueError:
            pass
    return sorted(agg.values(), key=lambda r: r["cpu"], reverse=True)


def get_top_processes(sort_key: str, limit: int = 10) -> list[dict]:
    flag = "-pcpu" if sort_key == "cpu" else "-pmem"
    out = run(
        ["ps", "-eo", "user,pid,pcpu,pmem,etime,args", "--sort=" + flag, "--no-headers"]
    )
    rows = []
    for line in out.splitlines()[:limit]:
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        user, pid, cpu, mem, etime, cmd = parts
        rows.append(
            {
                "user": user,
                "pid": pid,
                "cpu": float(cpu),
                "mem": float(mem),
                "etime": etime,
                "cmd": cmd[:120],
            }
        )
    return rows


def get_gpu() -> list[dict] | None:
    if not shutil.which("nvidia-smi"):
        return None
    out = run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
    )
    if not out.strip():
        return None
    gpus = []
    for line in out.splitlines():
        fields = [f.strip() for f in line.split(",")]
        if len(fields) != 6:
            continue
        idx, name, util, mem_used, mem_total, temp = fields
        gpus.append(
            {
                "index": idx,
                "name": name,
                "util_pct": float(util),
                "mem_used_mib": float(mem_used),
                "mem_total_mib": float(mem_total),
                "temp_c": float(temp),
            }
        )
    return gpus


def build_flags(disks: list[dict], system: dict) -> list[dict]:
    """The same "is this bad" judgment the dashboard shows, in one
    place, so the email alerter fires on exactly what the dashboard
    is showing red -- never a metric the UI considers fine."""
    flags = []
    for d in disks:
        if d["severity"] != "ok":
            flags.append(
                {
                    "id": f"disk:{d['mount']}",
                    "level": d["severity"],
                    "message": (
                        f"{d['mount']} is at {d['use_pct']}% used "
                        f"({human_bytes(d['avail_bytes'])} free)"
                    ),
                }
            )

    ratio = system["load1"] / max(system["ncpu"], 1)
    sev = severity(ratio, THRESHOLDS["load_warn_ratio"], THRESHOLDS["load_crit_ratio"])
    if sev != "ok":
        flags.append(
            {
                "id": "load",
                "level": sev,
                "message": (
                    f"Load average {system['load1']:.1f} is {ratio:.1f}x "
                    f"the {system['ncpu']} cores"
                ),
            }
        )

    mem = system.get("memory", {})
    if mem.get("swap_total"):
        swap_pct = 100 * mem["swap_used"] / mem["swap_total"]
        sev = severity(
            swap_pct, THRESHOLDS["swap_warn_pct"], THRESHOLDS["swap_crit_pct"]
        )
        if sev != "ok":
            flags.append(
                {"id": "swap", "level": sev, "message": f"Swap is {swap_pct:.0f}% used"}
            )
    return flags


def build_status() -> dict:
    disks = get_disks()
    system = get_load_and_memory()
    return {
        "generated_at": time.time(),
        "hostname": run(["hostname"]).strip(),
        "disks": disks,
        "system": system,
        "users": get_users(),
        "top_cpu": get_top_processes("cpu"),
        "top_mem": get_top_processes("mem"),
        "gpus": get_gpu(),
        "flags": build_flags(disks, system),
    }


def send_email(subject: str, body: str) -> None:
    to_addr = os.environ.get("ALERT_EMAIL_TO", "").strip()
    if not to_addr:
        return  # alerting is opt-in; no recipient means do nothing

    msg = email.message.EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get(
        "ALERT_EMAIL_FROM", f"lab-status@{socket.gethostname()}"
    )
    msg["To"] = to_addr
    msg.set_content(body)

    host = os.environ.get("SMTP_HOST", "localhost")
    port = int(os.environ.get("SMTP_PORT", "25"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    use_tls = os.environ.get("SMTP_USE_TLS", "false").lower() == "true"

    with smtplib.SMTP(host, port, timeout=10) as smtp:
        if use_tls:
            smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)


# Tracks, per flag id, when we last emailed about it -- so a
# still-critical disk re-alerts on a cooldown instead of every check,
# and clears once the flag disappears so a fresh alert fires promptly
# if it comes back.
_alert_last_sent: dict[str, float] = {}


def check_alerts() -> None:
    cooldown = int(os.environ.get("ALERT_COOLDOWN_MINUTES", "60")) * 60
    status = build_status()
    critical = {f["id"]: f for f in status["flags"] if f["level"] == "critical"}
    now = time.time()

    for fid, flag in critical.items():
        last = _alert_last_sent.get(fid)
        if last is None or (now - last) >= cooldown:
            send_email(
                f"[lab-status] CRITICAL on {status['hostname']}: {flag['message']}",
                f"{flag['message']}\n\nHost: {status['hostname']}\n"
                "This will re-alert every "
                f"{cooldown // 60} minutes while it stays critical.",
            )
            _alert_last_sent[fid] = now

    for fid in list(_alert_last_sent):
        if fid not in critical:
            send_email(
                f"[lab-status] RECOVERED on {status['hostname']}: {fid}",
                f"{fid} on {status['hostname']} is no longer critical.",
            )
            del _alert_last_sent[fid]


def alert_loop() -> None:
    interval = int(os.environ.get("ALERT_CHECK_INTERVAL_SECONDS", "60"))
    while True:
        try:
            check_alerts()
        except Exception as e:
            print(f"lab-status: alert check failed: {e}")
        time.sleep(interval)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet; use journalctl for logs under systemd

    def do_GET(self):
        if self.path == "/api/status":
            body = json.dumps(build_status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        path = "index.html" if self.path in ("/", "") else self.path.lstrip("/")
        file_path = (STATIC_DIR / path).resolve()
        if STATIC_DIR.resolve() not in file_path.parents or not file_path.is_file():
            self.send_error(404)
            return
        content_type = "text/html" if file_path.suffix == ".html" else "application/octet-stream"
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="bind address")
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument(
        "--test-alert",
        action="store_true",
        help="send one test email using the current ALERT_* env vars, then exit",
    )
    args = parser.parse_args()

    if args.test_alert:
        if not os.environ.get("ALERT_EMAIL_TO", "").strip():
            raise SystemExit("ALERT_EMAIL_TO is not set -- nothing to send to.")
        send_email(
            f"[lab-status] test alert from {socket.gethostname()}",
            "If you're reading this, email alerting is configured correctly.",
        )
        print(f"Test email sent to {os.environ['ALERT_EMAIL_TO']}")
        return

    threading.Thread(target=alert_loop, daemon=True).start()
    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"lab-status dashboard on http://{args.host}:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
