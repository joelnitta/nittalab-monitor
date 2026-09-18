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
import http.server
import json
import shutil
import subprocess
import time
from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"


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
        disks.append(
            {
                "filesystem": fs,
                "type": fstype,
                "mount": mount,
                "size_bytes": size_b,
                "used_bytes": used_b,
                "avail_bytes": avail_b,
                "use_pct": int(use_pct.rstrip("%") or 0),
            }
        )
    return disks


def get_load_and_memory() -> dict:
    loadavg = run(["cat", "/proc/loadavg"]).split()
    load1, load5, load15 = (
        (float(loadavg[i]) for i in range(3)) if len(loadavg) >= 3 else (0, 0, 0)
    )
    ncpu = 1
    try:
        import os

        ncpu = os.cpu_count() or 1
    except Exception:
        pass

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


def build_status() -> dict:
    return {
        "generated_at": time.time(),
        "hostname": run(["hostname"]).strip(),
        "disks": get_disks(),
        "system": get_load_and_memory(),
        "users": get_users(),
        "top_cpu": get_top_processes("cpu"),
        "top_mem": get_top_processes("mem"),
        "gpus": get_gpu(),
    }


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
    args = parser.parse_args()

    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"lab-status dashboard on http://{args.host}:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
