"""待ち受け中の開発サーバーを lsof で探す（macOS / Linux）。"""
import os
import subprocess

DEV_CMDS = ("node", "bun", "deno", "python", "ruby", "php", "java", "uvicorn", "gunicorn", "vite", "next-server")


def dev_ports():
    """[(起動フォルダ, ポート, コマンド名)] を返す。"""
    try:
        r = subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpcn"], capture_output=True, text=True)
    except OSError:
        return []
    procs, pid = {}, None
    for line in r.stdout.splitlines():
        k, v = line[:1], line[1:]
        if k == "p":
            pid = int(v)
            procs.setdefault(pid, {"cmd": "", "ports": set()})
        elif k == "c" and pid:
            procs[pid]["cmd"] = v
        elif k == "n" and pid:
            port = v.rsplit(":", 1)[-1]
            if port.isdigit():
                procs[pid]["ports"].add(int(port))
    me = os.getpid()
    pids = [p for p, i in procs.items()
            if p != me and i["ports"] and i["cmd"].lower().startswith(DEV_CMDS)]
    if not pids:
        return []
    r = subprocess.run(["lsof", "-a", "-d", "cwd", "-p", ",".join(map(str, pids)), "-Fpn"],
                       capture_output=True, text=True)
    out, pid = [], None
    for line in r.stdout.splitlines():
        if line[:1] == "p":
            pid = int(line[1:])
        elif line[:1] == "n" and pid in procs:
            cwd = os.path.realpath(line[1:])
            for port in sorted(procs[pid]["ports"]):
                out.append((cwd, port, procs[pid]["cmd"]))
    return out


def assign_ports(worktrees, ports):
    """起動フォルダがいちばん深く一致する worktree に割り当てる（本体の中に worktree があるため）。"""
    roots = sorted(((os.path.realpath(w["path"]), w) for w in worktrees if not w["missing"]), key=lambda x: -len(x[0]))
    for cwd, port, cmd in ports:
        for root, w in roots:
            if cwd == root or cwd.startswith(root + os.sep):
                if all(p["port"] != port for p in w["ports"]):
                    w["ports"].append({"port": port, "cmd": cmd})
                break
