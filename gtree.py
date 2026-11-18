#!/usr/bin/env python3
"""gtree: 複数リポジトリ × worktree × フォルダ階層 で差分を見る（読み取り専用）。

  gtree                  # 設定ファイルのリポジトリをブラウザで開く
  gtree ~/dev/a ~/dev/b  # その場でリポジトリを指定して開く
  gtree --init           # 今いるリポジトリで設定ファイルを作る
  gtree --cli            # ターミナルにツリーを出す
  gtree --port N         # ポートを指定（既定 7801）
  gtree --no-open        # ブラウザを自動で開かない

設定ファイル: $GTREE_CONFIG または ~/.config/gtree/config.json（README 参照）

各 worktree について
  - 未コミットの変更（git status）
  - ベースブランチ（origin/HEAD → なければ origin/main / develop / master）から
    このブランチで足したコミットの変更（merge-base..HEAD）
をまとめて 1 本のツリーにする。git に書き込む操作は一切しない。
"""
import json
import mimetypes
import re
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MAX_DIFF_LINES = 6000
HOME = os.path.expanduser("~")
CONFIG_PATH = os.path.expanduser(os.environ.get("GTREE_CONFIG", "~/.config/gtree/config.json"))
REPOS = []   # [{"path", "color", "icon"(svg 文字列)}]  起動時に load_repos() で埋める


# ---------------------------------------------------------------- config

def repo_root(path):
    """worktree の中から呼ばれても、本体（メインの worktree）のパスを返す。"""
    common = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    if not common:
        return ""
    return os.path.dirname(common) if os.path.basename(common) == ".git" else common


def load_icon(entry):
    p = entry.get("icon")
    if not p:
        return ""
    try:
        with open(os.path.expanduser(p), encoding="utf-8") as fh:
            svg = fh.read()
    except OSError:
        print(f"gtree: アイコンを読めませんでした: {p}", file=sys.stderr)
        return ""
    for src, dst in (entry.get("recolor") or {}).items():
        svg = svg.replace(src, dst)
    return svg


def load_repos(args):
    """引数 > 設定ファイル > 今いるリポジトリ の順でリポジトリ一覧を決める。"""
    entries = [{"path": a} for a in args]
    if not entries and os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            conf = json.load(fh)
        entries = [e if isinstance(e, dict) else {"path": e} for e in conf.get("repos", [])]
    if not entries:
        root = repo_root(os.getcwd())
        if root:
            entries = [{"path": root}]
    repos = []
    for e in entries:
        path = os.path.expanduser(e["path"])
        root = repo_root(path) if os.path.isdir(path) else ""
        if not root:
            print(f"gtree: git リポジトリではありません: {e['path']}", file=sys.stderr)
            continue
        repos.append({"path": root, "color": e.get("color", ""), "icon": load_icon(e)})
    return repos


def init_config():
    root = repo_root(os.getcwd())
    if not root:
        sys.exit("gtree --init は git リポジトリの中で実行してください")
    if os.path.exists(CONFIG_PATH):
        sys.exit(f"設定ファイルはもうあります: {CONFIG_PATH}")
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump({"repos": [{"path": root.replace(HOME, "~", 1)}]}, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"作りました: {CONFIG_PATH}\n見たいリポジトリを repos に足していってください。")


# ---------------------------------------------------------------- git

def git(path, *args, ok=(0,)):
    r = subprocess.run(["git", "-c", "core.quotepath=off", "-C", path, *args],
                       capture_output=True, text=True, errors="replace")
    return r.stdout if r.returncode in ok else ""


def base_ref(repo):
    ref = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
    if ref:
        return ref
    for cand in ("origin/main", "origin/develop", "origin/master"):
        if git(repo, "rev-parse", "--verify", "-q", cand).strip():
            return cand
    return ""


def remote_web(repo):
    """origin の URL を https://github.com/owner/repo の形にする（認証情報は落とす）。"""
    url = git(repo, "remote", "get-url", "origin").strip()
    if not url:
        return ""
    m = re.match(r"^[\w.-]+@([^:]+):(.+?)(?:\.git)?/?$", url)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    m = re.match(r"^(?:https?|ssh)://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+?)(?:\.git)?/?$", url)
    return f"https://{m.group(1)}/{m.group(2)}" if m else ""


def list_worktrees(repo):
    out, cur = [], {}
    for line in git(repo, "worktree", "list", "--porcelain").splitlines() + [""]:
        if not line:
            if cur:
                out.append(cur)
            cur = {}
            continue
        k, _, v = line.partition(" ")
        cur[k] = v or True
    return out


def numstat(path, *rng):
    stats = {}
    for line in git(path, "diff", "--numstat", *rng).splitlines():
        a, d, f = line.split("\t", 2)
        if " => " in f:
            f = f.split(" => ")[-1].replace("}", "")
        stats[f] = (a, d)
    return stats


def short_path(path):
    s = path.replace(HOME, "~")
    if "/scratchpad/" in s:
        s = "…/scratchpad/" + s.split("/scratchpad/")[-1]
    return s


DEV_CMDS = ("node", "bun", "deno", "python", "ruby", "php", "java", "uvicorn", "gunicorn", "vite", "next-server")


def dev_ports():
    """待ち受け中の開発サーバーを [(起動フォルダ, ポート, コマンド名)] で返す。"""
    r = subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpcn"], capture_output=True, text=True)
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


def collect():
    """全リポジトリ・全 worktree の変更をまとめる。WT[path] に merge-base を覚える。"""
    repos = []
    wt_index = {}
    ports = dev_ports()
    all_wts = []
    for conf in REPOS:
        repo = conf["path"]
        if not os.path.isdir(repo):
            continue
        base = base_ref(repo)
        wts = []
        for wt in list_worktrees(repo):
            path = wt["worktree"]
            branch = wt.get("branch", "(detached)").replace("refs/heads/", "")
            item = {"path": path, "short": short_path(path), "branch": branch,
                    "missing": not os.path.isdir(path), "files": []}
            wts.append(item)
            all_wts.append(item)
            item["ports"] = []
            if item["missing"]:
                continue
            mb = git(path, "merge-base", base, "HEAD").strip() if base else ""
            files = {}
            if mb:
                ns = numstat(path, f"{mb}..HEAD")
                for line in git(path, "diff", "--name-status", f"{mb}..HEAD").splitlines():
                    parts = line.split("\t")
                    f = parts[-1]
                    a, d = ns.get(f, ("", ""))
                    files[f] = {"path": f, "st": parts[0][0], "kind": "commit", "add": a, "del": d}
            ns = numstat(path, "HEAD")
            untracked = []
            for line in git(path, "status", "--porcelain=v1", "-unormal").splitlines():
                xy, f = line[:2], line[3:]
                if " -> " in f:
                    f = f.split(" -> ")[-1]
                f = f.strip('"')
                if xy == "??":
                    untracked.append(f)
                    is_dir = f.endswith("/")
                    files[f.rstrip("/")] = {"path": f.rstrip("/"), "st": "A", "kind": "wip",
                                            "untracked": True, "dir": is_dir, "add": "", "del": ""}
                    continue
                st = (xy.replace(" ", "") or "M")[0]
                a, d = ns.get(f, ("", ""))
                prev = files.get(f)
                files[f] = {"path": f, "st": prev["st"] if prev and prev["st"] == "A" else st,
                            "kind": "both" if prev else "wip", "add": a, "del": d}
            # 新規フォルダの中身の数
            for f in untracked:
                if f.endswith("/"):
                    n = len(git(path, "ls-files", "--others", "--exclude-standard", f).splitlines())
                    files[f.rstrip("/")]["count"] = n
            item["files"] = sorted(files.values(), key=lambda x: x["path"])
            wt_index[os.path.realpath(path)] = {"mb": mb, "base": base}
        repos.append({"name": os.path.basename(repo), "base": base, "remote": remote_web(repo),
                      "color": conf["color"], "icon": bool(conf["icon"]), "worktrees": wts})
    # 起動フォルダがいちばん深く一致する worktree に割り当てる（本体の中に worktree があるため）
    roots = sorted(((os.path.realpath(w["path"]), w) for w in all_wts if not w["missing"]), key=lambda x: -len(x[0]))
    for cwd, port, cmd in ports:
        for root, w in roots:
            if cwd == root or cwd.startswith(root + os.sep):
                if all(p["port"] != port for p in w["ports"]):
                    w["ports"].append({"port": port, "cmd": cmd})
                break
    return repos, wt_index


WT = {}  # realpath -> {"mb", "base"}
LOCK = threading.Lock()


def refresh():
    repos, idx = collect()
    with LOCK:
        WT.clear()
        WT.update(idx)
    return repos


def safe_target(wt, f):
    """worktree が既知で、ファイルがその中にあるときだけ実パスを返す。"""
    real = os.path.realpath(wt)
    with LOCK:
        info = WT.get(real)
    if info is None:
        return None, None, None
    full = os.path.realpath(os.path.join(real, f))
    if full != real and not full.startswith(real + os.sep):
        return None, None, None
    return real, full, info


def file_diff(wt, f, untracked):
    real, full, info = safe_target(wt, f)
    if real is None:
        return None
    if untracked:
        out = git(real, "diff", "--no-index", "--", "/dev/null", f, ok=(0, 1))
    else:
        out = git(real, "diff", info["mb"] or "HEAD", "--", f)
    lines = out.splitlines()
    truncated = len(lines) > MAX_DIFF_LINES
    return {"diff": "\n".join(lines[:MAX_DIFF_LINES]), "truncated": truncated,
            "base": info["base"], "exists": os.path.isfile(full)}


def list_untracked(wt, d):
    real, _, _ = safe_target(wt, d)
    if real is None:
        return None
    return git(real, "ls-files", "--others", "--exclude-standard", d.rstrip("/") + "/").splitlines()


# ---------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/":
            return self.send(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/api/tree":
            return self.send(200, json.dumps({"repos": refresh()}, ensure_ascii=False))
        if u.path == "/api/diff":
            r = file_diff(q.get("wt", ""), q.get("f", ""), q.get("u") == "1")
            return self.send(200, json.dumps(r, ensure_ascii=False)) if r else self.send(404, "{}")
        if u.path == "/api/icon":
            svg = next((r["icon"] for r in REPOS if os.path.basename(r["path"]) == q.get("r")), "")
            return self.send(200, svg, "image/svg+xml") if svg else self.send(404, "", "text/plain")
        if u.path == "/api/ls":
            r = list_untracked(q.get("wt", ""), q.get("d", ""))
            return self.send(200, json.dumps(r, ensure_ascii=False)) if r is not None else self.send(404, "[]")
        if u.path == "/api/raw":
            real, full, _ = safe_target(q.get("wt", ""), q.get("f", ""))
            if not real or not os.path.isfile(full):
                return self.send(404, "not found", "text/plain")
            with open(full, "rb") as fh:
                data = fh.read()
            ctype = mimetypes.guess_type(full)[0] or "text/plain; charset=utf-8"
            if ctype.startswith("text/") and "charset" not in ctype:
                ctype += "; charset=utf-8"
            return self.send(200, data, ctype)
        self.send(404, "not found", "text/plain")


def serve(port):
    for p in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            break
        except OSError:
            continue
    else:
        sys.exit("空いているポートが見つかりませんでした")
    url = f"http://127.0.0.1:{p}/"
    print(f"gtree: {url}  （止めるときは Ctrl+C）")
    if "--no-open" not in sys.argv:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------- cli

def cli():
    tty = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    c = (lambda code, s: f"\033[{code}m{s}\033[0m") if tty else (lambda code, s: s)
    color = {"A": "32", "M": "33", "D": "31", "R": "36"}
    for repo in refresh():
        print(c("1", f"■ {repo['name']}") + "  " + c("2", f"base: {repo['base'] or '-'}"))
        wts = [w for w in repo["worktrees"] if w["files"] or w["missing"]]
        for j, w in enumerate(wts):
            last = j == len(wts) - 1
            print(("└─ " if last else "├─ ") + c("1", f"⎇ {w['branch']}") + "  " + c("2", w["short"]))
            pre = "   " if last else "│  "
            if w["missing"]:
                print(pre + c("2", "(フォルダなし・prune 可)"))
            for f in w["files"]:
                extra = f" (新規フォルダ・{f.get('count', 0)} ファイル)" if f.get("dir") else \
                    (f" +{f['add']} -{f['del']}" if f["add"] not in ("", "-") else "")
                tag = {"commit": " (commit済)", "both": " (commit済+未コミット)"}.get(f["kind"], "")
                print(pre + c(color.get(f["st"], "0"), f"{f['st']} {f['path']}") + c("2", extra + tag))
        print()


# ---------------------------------------------------------------- page

PAGE = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GTREE</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect width='24' height='24' rx='6' fill='%2337352f'/%3E%3Cpath d='M8 5.5v13M8 9.5c0 3.5 8 1.5 8 5.5v1' stroke='%23fff' stroke-width='1.8' fill='none' stroke-linecap='round'/%3E%3Ccircle cx='8' cy='5.5' r='2' fill='%23fff'/%3E%3Ccircle cx='8' cy='18.5' r='2' fill='%23fff'/%3E%3Ccircle cx='16' cy='17' r='2' fill='%233cadba'/%3E%3C/svg%3E">
<style>
:root{--hh:96px;--bg:#fff;--panel:#fbfbfa;--fg:#37352f;--sub:#73726e;--mu:#9b9a97;--bd:#ebeae7;--hover:rgba(55,53,47,.08);--hover2:rgba(55,53,47,.12);
--sel:#e7f0fa;--selfg:#0c447c;--card:#fff;--cardbd:#e9e8e4;--logo:#37352f;
--add:#edf6e8;--addfg:#2f6b12;--del:#fcecec;--delfg:#b03a3a;--mod:#9a6400;--hunk:#f4f3f0;--blue:#2f6fb0;
--chip-amber:#fbf0dc;--chip-amberfg:#8a5a0b;--chip:#f1f0ec}
@media (prefers-color-scheme:dark){:root{--bg:#191919;--panel:#202020;--fg:#e6e5e1;--sub:#a5a49f;--mu:#7d7c78;--bd:#2f2f2f;--hover:rgba(255,255,255,.07);--hover2:rgba(255,255,255,.11);
--sel:#18324d;--selfg:#b5d4f4;--card:#252525;--cardbd:#333;--logo:#e6e5e1;
--add:#17301b;--addfg:#97c459;--del:#3a1818;--delfg:#f09595;--mod:#efa634;--hunk:#262625;--blue:#85b7eb;
--chip-amber:#3b2e15;--chip-amberfg:#f2c46d;--chip:#2c2c2b}}
*{box-sizing:border-box;scrollbar-width:none}
*::-webkit-scrollbar{display:none}
html,body{margin:0;height:100%;overflow:hidden;background:var(--bg);color:var(--fg);font:13px/1.5 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Segoe UI",sans-serif}
.app{position:relative;display:grid;grid-template-columns:var(--lw,340px) minmax(0,1fr);height:100vh;overflow:hidden}
.side{display:flex;flex-direction:column;background:var(--panel);border-right:1px solid var(--bd);min-width:0;min-height:0;overflow:hidden}
.side-top{height:var(--hh);flex:none;display:flex;flex-direction:column;justify-content:center;gap:10px;border-bottom:1px solid var(--bd)}
.brand{display:flex;align-items:center;gap:9px;padding:0 14px}
.brand .wm{font-weight:700;letter-spacing:.16em;font-size:13px}
.brand .tag{color:var(--mu);font-size:11px;margin-left:auto;display:flex;align-items:center;gap:5px}
.dot{width:6px;height:6px;border-radius:50%;background:#3cadba;display:inline-block}
.dot.busy{background:#e0a030}
.tools{padding:0 10px;display:flex;align-items:center;gap:6px;}
.search{flex:1;min-width:0;height:28px;border:1px solid var(--bd);border-radius:6px;padding:0 8px;background:var(--bg);color:var(--fg);width:100%;font:inherit}
.search:focus{outline:none;border-color:var(--blue)}
.seg{display:flex;flex:none;height:28px;background:var(--chip);border-radius:6px;padding:2px;gap:2px}
.seg button{width:26px;height:24px;display:grid;place-items:center;padding:0;border:0;border-radius:4px;background:transparent;color:var(--sub);cursor:pointer;font:inherit;font-size:12px}
.seg button.on{background:var(--bg);color:var(--fg);box-shadow:0 0 0 1px var(--bd)}
.tree{overflow:auto;flex:1;min-height:0;padding-bottom:30px}
.repo-sec{--tint:color-mix(in srgb,var(--c) 9%,var(--panel));background:var(--tint);padding-bottom:10px;border-bottom:1px solid var(--bd)}
.repo-h{position:sticky;top:0;z-index:2;background:var(--tint);display:flex;align-items:center;gap:9px;padding:10px 12px 6px;cursor:pointer;user-select:none}
.repo-h .ic{min-width:20px;padding:0 4px;height:20px;font-size:10px!important;border-radius:5px;display:grid;place-items:center;font-size:11px;font-weight:700;color:#fff;flex:none}
.repo-h .rl{flex:none;display:block}
.repo-h .nm{font-weight:600;font-size:14px}
.repo-h .base{font-size:11px;color:var(--mu);background:var(--chip);border-radius:4px;padding:0 5px}
.repo-h .chev{margin-left:auto;color:var(--mu);font-size:11px}
.repo-empty{color:var(--mu);font-size:12px;padding:0 12px 6px 40px}
.wt{margin:1px 6px}
.repo-h{padding-left:12px!important;padding-top:12px!important}
.wt-h{display:flex;align-items:center;gap:6px;padding:4px 8px 4px 6px;border-radius:6px;cursor:pointer;user-select:none}
.wt-h:hover{background:var(--hover2)}
.wt-h .br{font-weight:600;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.wt-h svg{flex:none;color:var(--mu)}
.wt-h.is-main svg{color:var(--fg)}
.kind{font-size:11px;color:var(--mu);flex:none}
.chips{margin-left:auto;display:flex;gap:4px;flex:none}
.port{display:inline-flex;align-items:center;gap:4px;font-size:10.5px;font-family:ui-monospace,Menlo,monospace;border-radius:4px;padding:0 6px;background:var(--bg);color:var(--fg);border:1px solid var(--bd);text-decoration:none}
.port:hover{border-color:var(--blue);color:var(--blue)}
.pd{width:6px;height:6px;border-radius:50%;background:#3cadba}
.chip{font-size:10.5px;border-radius:4px;padding:0 5px;background:var(--chip);color:var(--sub)}
.chip.w{background:var(--chip-amber);color:var(--chip-amberfg)}
.wt-b{margin:0 0 6px 10px;border-left:1px solid var(--bd);padding:1px 0 1px 2px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.row{display:flex;align-items:center;gap:4px;padding:0 8px 0 0;cursor:pointer;white-space:nowrap;line-height:23px;border-radius:4px;margin:0 4px}
.row:hover{background:var(--hover2)}
.row.msel{background:var(--sel);color:var(--selfg)}
#cmenu{position:fixed;z-index:50;min-width:240px;max-width:420px;background:var(--bg);border:1px solid var(--bd);border-radius:8px;padding:4px;box-shadow:0 8px 24px rgba(0,0,0,.12),0 2px 6px rgba(0,0,0,.08)}
#cmenu .mh{font-size:11px;color:var(--mu);padding:4px 10px 6px}
#cmenu button{display:flex;flex-direction:column;align-items:flex-start;gap:1px;width:100%;border:0;background:transparent;color:var(--fg);text-align:left;padding:6px 10px;border-radius:5px;cursor:pointer;font:inherit}
#cmenu button:hover{background:var(--hover2)}
#cmenu .ex{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--mu);max-width:390px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%) translateY(10px);background:var(--fg);color:var(--bg);padding:7px 14px;border-radius:8px;font-size:12px;opacity:0;pointer-events:none;transition:.18s}
#toast.on{opacity:1;transform:translateX(-50%)}
.row.sel{background:var(--sel);color:var(--selfg)}
.tw{width:12px;text-align:center;color:var(--mu);flex:none;font-size:10px}
.nm{overflow:hidden;text-overflow:ellipsis;min-width:0}
.dir{color:var(--sub)}
.cnt{color:var(--mu);margin-left:auto;padding-left:8px;font-size:11px;flex:none}
.st{width:13px;flex:none;font-weight:700;font-size:11px}
.st-A{color:var(--addfg)} .nm.st-D,.p.st-D{text-decoration:line-through} .st-M{color:var(--mod)} .st-D{color:var(--delfg)} .st-R{color:var(--blue)}
.badge{font-size:10px;border-radius:4px;padding:0 4px;background:var(--chip);color:var(--sub);margin-left:4px;flex:none;font-family:-apple-system,sans-serif}
.badge.w{background:var(--chip-amber);color:var(--chip-amberfg)}
.wd{width:6px;height:6px;border-radius:50%;background:#e0a030;flex:none;margin-left:6px}
.new{box-shadow:inset 2px 0 0 #e0a030}
.drag{position:absolute;top:0;bottom:0;left:calc(var(--lw,340px) - 3px);width:6px;z-index:5;cursor:col-resize}.drag:hover{background:var(--bd)}
.main{display:flex;flex-direction:column;min-width:0;min-height:0;overflow:hidden}
.head{background:var(--panel);height:var(--hh);padding:0 32px;border-bottom:1px solid var(--bd);flex:none;display:flex;flex-direction:column;justify-content:center;gap:6px;min-width:0}
.head .hint{color:var(--mu)}
.crumb{color:var(--mu);font-size:12px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.line2{display:flex;gap:12px;align-items:center;min-width:0}
.line2 .p{font-family:ui-monospace,Menlo,monospace;font-weight:600;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;direction:rtl;text-align:left;min-width:0;flex:0 1 auto}
.line2>*:not(.p){flex:none}
.vs{margin-left:auto;display:flex;background:var(--chip);border-radius:6px;padding:2px;gap:2px}
.vs button{height:24px;border:0;border-radius:4px;background:transparent;color:var(--sub);cursor:pointer;font:inherit;font-size:12px;padding:0 10px}
.vs button.on{background:var(--bg);color:var(--fg);box-shadow:0 0 0 1px var(--bd)}
.body{overflow:auto;flex:1;min-height:0}
table.d{border-collapse:collapse;width:100%;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.body{padding:0}
table.d td{padding:0 14px;white-space:pre-wrap;word-break:break-all;vertical-align:top;line-height:22px}
table.d td.n{width:1%;min-width:46px;text-align:right;color:var(--mu);user-select:none;white-space:nowrap}
tr.a td{background:var(--add)} tr.a td.c{color:var(--addfg)}
tr.r td{background:var(--del)} tr.r td.c{color:var(--delfg)}
tr.h td{background:var(--hunk);color:var(--mu)}
table.s{table-layout:fixed}
table.s td.n{min-width:0}
table.s td.c{width:auto}
table.s td.r{background:var(--del)} table.s td.c.r{color:var(--delfg)}
table.s td.a{background:var(--add)} table.s td.c.a{color:var(--addfg)}
table.s td.e{background:var(--hunk)}
table.s td.n:nth-child(3){border-left:1px solid var(--bd)}
.empty{color:var(--mu);padding:60px 20px;text-align:center}
.empty svg{opacity:.85;margin-bottom:10px}
.md{padding:16px 48px;max-width:920px;line-height:1.8}
.md table{border-collapse:collapse}.md td,.md th{border:1px solid var(--bd);padding:4px 8px}
.md pre{background:var(--panel);padding:10px;overflow:auto;border-radius:6px}.md code{font-size:12px}
.md img{max-width:100%;border:1px solid var(--bd);border-radius:4px}
.img{padding:16px 32px}.img img{max-width:100%;border:1px solid var(--bd);border-radius:4px}
pre.raw{margin:0;padding:8px 32px;line-height:1.7;font-size:12px;white-space:pre-wrap;word-break:break-all}
</style></head><body>
<div class="app" id="app">
 <aside class="side">
  <div class="side-top">
  <div class="brand">
   <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true"><rect width="24" height="24" rx="6" fill="var(--logo)"/><path d="M8 5.5v13M8 9.5c0 3.5 8 1.5 8 5.5v1" stroke="var(--bg)" stroke-width="1.8" fill="none" stroke-linecap="round"/><circle cx="8" cy="5.5" r="2" fill="var(--bg)"/><circle cx="8" cy="18.5" r="2" fill="var(--bg)"/><circle cx="16" cy="17" r="2" fill="#3cadba"/></svg>
   <span class="wm">GTREE</span>
   <span class="tag" id="status" title="5秒ごとに自動で読み直します"><span class="dot" id="dot"></span><span id="ago">読み込み中</span></span>
  </div>
  <div class="tools">
   <input class="search" type="search" id="q" placeholder="絞り込み（/）">
   <div class="seg" id="seg">
    <button data-v="all" class="on" title="すべて" aria-label="すべて"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4h10M3 8h10M3 12h10"/></svg></button><button data-v="wip" title="未コミットだけ" aria-label="未コミットだけ"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.5 2.5l3 3L6 13H3v-3z"/></svg></button><button data-v="commit" title="commit済だけ" aria-label="commit済だけ"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="2.6"/><path d="M1.5 8h3.9M10.6 8h3.9"/></svg></button>
   </div>
  </div>
  </div>
  <div class="tree" id="tree"></div>
 </aside>
 <div class="drag" id="drag"></div>
 <main class="main">
  <div class="head" id="head"><div class="hint">左のファイルを選ぶと、ここに差分が出ます</div></div>
  <div class="body" id="body"><div class="empty"><svg width="40" height="40" viewBox="0 0 24 24"><rect width="24" height="24" rx="6" fill="var(--logo)"/><path d="M8 5.5v13M8 9.5c0 3.5 8 1.5 8 5.5v1" stroke="var(--bg)" stroke-width="1.8" fill="none" stroke-linecap="round"/><circle cx="8" cy="5.5" r="2" fill="var(--bg)"/><circle cx="8" cy="18.5" r="2" fill="var(--bg)"/><circle cx="16" cy="17" r="2" fill="#3cadba"/></svg><div>左のファイルを選ぶと差分が出ます</div><div style="font-size:12px;margin-top:4px">j / k で移動 · / で絞り込み · r で今すぐ更新</div></div></div>
 </main>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<script>
const $=s=>document.querySelector(s);
const LS={get(k,d){try{return JSON.parse(localStorage.getItem(k))??d}catch{return d}},set(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch{}}};
const IMG=/\.(png|jpe?g|gif|webp|svg)$/i, MD=/\.mdx?$/i;
const ST={A:'追加（新しいファイル）',M:'変更',D:'削除',R:'名前の変更'};
const COLORS=['#3cadba','#f2b51d','#9a7ad8','#2f6fb0','#d16ba5'];
const BRANCH='<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="4" cy="3.5" r="1.6"/><circle cx="4" cy="12.5" r="1.6"/><circle cx="12" cy="5" r="1.6"/><path d="M4 5.1v5.8M12 6.6c0 3-8 1.5-8 4.3"/></svg>';
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let DATA=null, _v0=LS.get('gt.view','split'), RAW='', sel=LS.get('gt.sel',null), closed=new Set(LS.get('gt.closed',[])), loadedDirs={},
    view=_v0==='file'?'diff':_v0, filter=LS.get('gt.filter','all'), lastAt=0, busy=false, prevKeys=null, freshKeys=new Set();

async function load(manual){
  if(busy) return; busy=true; $('#dot').classList.add('busy');
  try{
    const txt=await (await fetch('/api/tree')).text(); lastAt=Date.now();
    if(txt!==RAW){
      const first=!RAW; RAW=txt; DATA=JSON.parse(txt).repos;
      const keys=new Map(); for(const r of DATA) for(const w of r.worktrees) for(const f of w.files) keys.set(w.path+'::'+f.path,f.add+'/'+f.del+'/'+f.kind);
      if(prevKeys&&!first){ for(const [k,v] of keys) if(prevKeys.get(k)!==v) freshKeys.add(k); }
      prevKeys=keys; loadedDirs={}; render();
      if(first){ // ?open=パス&branch=ブランチ で最初に開くファイルを指定できる
        const q=new URLSearchParams(location.search), op=q.get('open'), br=q.get('branch');
        if(op){ const r=[...document.querySelectorAll('.row[data-key]')].find(x=>{const i=INFO[x.dataset.p]; return i&&i.path===op&&(!br||i.branch===br);});
          if(r){ sel=null; r.click(); return; } }
      }
      if(sel){ const wt=DATA.flatMap(r=>r.worktrees.map(w=>({...w,repo:r.name}))).find(w=>w.path===sel.wt);
        const f=wt&&wt.files.find(x=>x.path===sel.path); if(f) sel.f={...f}; show(sel,{keep:!first}); }
    }
  }finally{busy=false; $('#dot').classList.remove('busy'); tick();}
}
function tick(){ if(!lastAt) return; const s=Math.round((Date.now()-lastAt)/1000); $('#ago').textContent=s<3?'最新':s+'秒前'; }
setInterval(tick,1000);
setInterval(()=>{ if(document.visibilityState==='visible') load(); },5000);
document.addEventListener('visibilitychange',()=>{ if(document.visibilityState==='visible') load(); });

function buildTree(files){
  const root={d:{},f:[]};
  for(const f of files){
    const parts=f.path.split('/'); let n=root;
    for(const p of parts.slice(0,-1)) n=n.d[p]??=({d:{},f:[]});
    const last=parts[parts.length-1];
    if(f.dir) n.d[last]={d:{},f:[],udir:f}; else n.f.push({...f,name:last});
  }
  return root;
}
function passFilter(f){
  const q=$('#q').value.trim().toLowerCase();
  if(filter==='wip'&&f.kind==='commit') return false;
  if(filter==='commit'&&f.kind==='wip') return false;
  if(q&&!f.path.toLowerCase().includes(q)) return false;
  return true;
}
function el(tag,cls,html){const e=document.createElement(tag); if(cls) e.className=cls; if(html!=null) e.innerHTML=html; return e;}
function row(depth,html,cls,key,onclick,info){
  const d=el('div','row '+(cls||''),html); d.style.paddingLeft=(6+depth*14)+'px';
  if(key) d.dataset.key=key;
  if(info){ const p=info.wt+'::'+info.path+(info.dir?'/':''); d.dataset.p=p; INFO[p]=info; if(msel.has(p)) d.classList.add('msel'); }
  d.onclick=e=>clickRow(e,d,onclick); return d;
}
const INFO={}; let msel=new Set(), anchor=null;
function paintSel(){ document.querySelectorAll('.row[data-p]').forEach(r=>r.classList.toggle('msel',msel.has(r.dataset.p))); }
function clickRow(e,d,action){
  const p=d.dataset.p;
  if(p&&(e.metaKey||e.ctrlKey)){ msel.has(p)?msel.delete(p):msel.add(p); anchor=p; paintSel(); return; }
  if(p&&e.shiftKey&&anchor){
    const rows=[...document.querySelectorAll('.row[data-p]')].map(r=>r.dataset.p), a=rows.indexOf(anchor), b=rows.indexOf(p);
    if(a>=0&&b>=0){ msel=new Set(rows.slice(Math.min(a,b),Math.max(a,b)+1)); paintSel(); return; }
  }
  if(p){ msel=new Set([p]); anchor=p; paintSel(); }
  action&&action(e);
}
function selected(){ return [...document.querySelectorAll('.row[data-p]')].map(r=>r.dataset.p).filter(p=>msel.has(p)).map(p=>INFO[p]); }
function fmt(i,kind){
  const tail=i.dir?'/':'';
  if(kind==='repo') return i.repo+'/'+i.path+tail;
  if(kind==='rel') return i.path+tail;
  if(kind==='abs') return i.wt+'/'+i.path+tail;
  if(kind==='remote') return i.remote?`${i.remote}/${i.dir?'tree':'blob'}/${i.branch.split('/').map(encodeURIComponent).join('/')}/${i.path.split('/').map(encodeURIComponent).join('/')}`:'';
}
async function copy(kind){
  const list=selected(); if(!list.length) return;
  const text=list.map(i=>fmt(i,kind)).filter(Boolean).join('\n');
  try{ await navigator.clipboard.writeText(text); }catch{ const t=el('textarea'); t.value=text; document.body.append(t); t.select(); document.execCommand('copy'); t.remove(); }
  toast(`${list.length}件のパスをコピーしました`);
}
function toast(msg){ let t=$('#toast'); if(!t){ t=el('div'); t.id='toast'; document.body.append(t); } t.textContent=msg; t.classList.add('on'); clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove('on'),1600); }
function closeMenu(){ $('#cmenu')?.remove(); }
document.addEventListener('contextmenu',e=>{
  const r=e.target.closest('.row[data-p]'); if(!r) return; e.preventDefault();
  if(!msel.has(r.dataset.p)){ msel=new Set([r.dataset.p]); anchor=r.dataset.p; paintSel(); }
  closeMenu(); const list=selected(), first=list[0], hasRemote=list.some(i=>i.remote);
  const m=el('div'); m.id='cmenu';
  const item=(k,label)=>`<button data-k="${k}"><span>${label}</span><span class="ex">${esc(fmt(first,k)||'')}</span></button>`;
  m.innerHTML=`<div class="mh">${list.length}件を選択中</div>${item('repo','リポジトリ名からのパス')}${item('rel','相対パス')}${item('abs','絶対パス')}${hasRemote?item('remote','リモートの URL'):''}`;
  document.body.append(m);
  const w=m.offsetWidth, h=m.offsetHeight;
  m.style.left=Math.min(e.clientX,innerWidth-w-8)+'px'; m.style.top=Math.min(e.clientY,innerHeight-h-8)+'px';
  m.querySelectorAll('button').forEach(b=>b.onclick=()=>{ copy(b.dataset.k); closeMenu(); });
});
document.addEventListener('mousedown',e=>{ if(!e.target.closest('#cmenu')) closeMenu(); });
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){ closeMenu(); if(msel.size>1){ msel=new Set(sel?[sel.wt+'::'+sel.path]:[]); paintSel(); } }
  if((e.metaKey||e.ctrlKey)&&e.key==='c'&&e.target.tagName!=='INPUT'&&!getSelection().toString()&&msel.size){ e.preventDefault(); copy('repo'); }
});
function saveClosed(){ LS.set('gt.closed',[...closed]); }
function toggle(key){ closed.has(key)?closed.delete(key):closed.add(key); saveClosed(); render(); }
function countFiles(n){ let c=n.f.length+(n.udir?(n.udir.count||0):0); for(const k in n.d) c+=countFiles(n.d[k]); return c; }

function renderDir(box,wt,node,depth,prefix){
  for(let name of Object.keys(node.d).sort()){
    let child=node.d[name], full=prefix+name;
    while(!child.udir&&child.f.length===0&&Object.keys(child.d).length===1){
      const k=Object.keys(child.d)[0]; name+='/'+k; full+='/'+k; child=child.d[k];
    }
    const key=wt.path+'::'+full+'/';
    if(child.udir){
      const open=closed.has(key+'!open'), list=loadedDirs[key];
      box.append(row(depth,`<span class="tw">${open?'▾':'▸'}</span><span class="nm st-A" title="新しいフォルダ">${esc(name)}/</span><span class="cnt">${child.udir.count||0}</span>`,'',null,async()=>{
        open?closed.delete(key+'!open'):closed.add(key+'!open'); saveClosed();
        if(!open&&!loadedDirs[key]) await loadDir(wt,full,key); render();
      },{wt:wt.path,repo:wt._repo,branch:wt.branch,remote:wt._remote,path:full,dir:true}));
      if(open&&list){
        const sub=buildTree(list.map(p=>({path:p.slice(full.length+1),st:'A',kind:'wip',untracked:true,add:'',del:''})));
        renderDir(box,wt,sub,depth+1,full+'/');
      } else if(open&&!list) loadDir(wt,full,key).then(render);
      continue;
    }
    const isClosed=closed.has(key);
    const sub=el('div'); renderDir(sub,wt,child,depth+1,full+'/');
    if(!sub.childElementCount) continue;
    box.append(row(depth,`<span class="tw">${isClosed?'▸':'▾'}</span><span class="nm dir">${esc(name)}/</span><span class="cnt">${countFiles(child)}</span>`,'',null,()=>toggle(key),{wt:wt.path,repo:wt._repo,branch:wt.branch,remote:wt._remote,path:full,dir:true}));
    if(!isClosed) box.append(...sub.childNodes);
  }
  for(const f of node.f.sort((a,b)=>a.name.localeCompare(b.name))){
    const path=prefix+f.name, ff={...f,path};
    if(!passFilter(ff)) continue;
    const key=wt.path+'::'+path;
    const stat=f.add&&f.add!=='-'?`<span class="cnt"><span class="st-A">+${f.add}</span> <span class="st-D">−${f.del}</span></span>`:'<span class="cnt"></span>';
    const tag=f.kind!=='commit'?'<span class="wd" title="未コミットの変更あり"></span>':'';
    box.append(row(depth,`<span class="tw"></span><span class="nm st-${f.st}" title="${ST[f.st]||''}">${esc(f.name)}</span>${tag}${stat}`,
      (sel&&sel.key===key?'sel ':'')+(freshKeys.has(key)?'new':''),key,()=>{freshKeys.delete(key); show({key,wt:wt.path,path,f:ff,repo:wt._repo,branch:wt.branch},{scroll:true});},{wt:wt.path,repo:wt._repo,branch:wt.branch,remote:wt._remote,path,dir:false}));
  }
}
async function loadDir(wt,d,key){
  loadedDirs[key]=await (await fetch('/api/ls?'+new URLSearchParams({wt:wt.path,d}))).json();
}
function render(){
  const tree=$('#tree'), top=tree.scrollTop; tree.innerHTML=''; try{localStorage.removeItem('gt.paneW')}catch{}
  DATA.forEach((repo,i)=>{
    const rk='repo::'+repo.name, rc=closed.has(rk);
    const live=repo.worktrees.filter(w=>w.files.length||w.missing||(w.ports&&w.ports.length));
    const h=el('div','repo-h',`${repo.icon?`<img class="rl" src="/api/icon?r=${encodeURIComponent(repo.name)}" width="30" height="26" alt="">`:`<span class="ic" style="background:${repo.color||COLORS[i%COLORS.length]}">${esc((n=>n.length<=3?n:n.slice(0,2))(repo.name.replace(/^[^-]+-/,'')).toUpperCase())}</span>`}<span class="nm">${esc(repo.name)}</span><span class="base">${esc((repo.base||'').replace('origin/',''))}</span><span class="chev">${rc?'▸':'▾'}</span>`);
    const sec=el('div','repo-sec'); sec.style.setProperty('--c',repo.color||COLORS[i%COLORS.length]); tree.append(sec);
    h.onclick=()=>toggle(rk); sec.append(h);
    if(rc) return;
    const body=sec;
    if(!live.length){ body.append(el('div','repo-empty','変更なし')); return; }
    live.forEach(wt=>{
      wt._repo=repo.name; wt._remote=repo.remote;
      const wk='wt::'+wt.path, wc=closed.has(wk);
      const nw=wt.files.filter(f=>f.kind!=='commit').length, nc=wt.files.filter(f=>f.kind!=='wip').length;
      const isMain=wt===repo.worktrees[0];
      const card=el('div','wt');
      const head=el('div','wt-h'+(isMain?' is-main':''),`<span class="tw">${wc?'▸':'▾'}</span>${BRANCH}<span class="br">${esc(wt.branch)}</span>
        <span class="chips">${(wt.ports||[]).map(p=>`<a class="port" href="http://localhost:${p.port}" target="_blank" title="${esc(p.cmd)} が http://localhost:${p.port} で動いています（クリックで開く）"><span class="pd"></span>:${p.port}</a>`).join('')}${wt.missing?'<span class="chip">フォルダなし</span>':''}${nw?`<span class="chip w">未 ${nw}</span>`:''}${nc?`<span class="chip">済 ${nc}</span>`:''}</span>`);
      head.title=wt.path; head.onclick=e=>{ if(e.target.closest('.port')) return; toggle(wk); }; card.append(head);
      if(!wc&&!wt.missing){ const b=el('div','wt-b'); renderDir(b,wt,buildTree(wt.files),0,''); if(!b.childElementCount) b.append(el('div','repo-empty','この絞り込みでは該当なし')); card.append(b); }
      body.append(card);
    });
  });
  tree.scrollTop=top;
}
async function show(s,opt={}){
  sel=s; LS.set('gt.sel',s);
  document.querySelectorAll('.row.sel').forEach(e=>e.classList.remove('sel'));
  const r=document.querySelector(`.row[data-key="${CSS.escape(s.key)}"]`); r?.classList.add('sel');
  if(opt.scroll) r?.scrollIntoView({block:'nearest'});
  const f=s.f, canView=f.st!=='D';
  const kind={commit:'commit済',wip:f.untracked?'新規（未追跡）':'未コミット',both:'commit済 + 未コミット'}[f.kind];
  const stat=f.add&&f.add!=='-'?`<span class="st-A">+${f.add}</span> <span class="st-D">−${f.del}</span>`:'';
  const head=$('#head'); head.hidden=false;
  head.innerHTML=`<div class="crumb">${esc(s.repo||'')} <span>›</span> ${BRANCH} ${esc(s.branch||'')}</div>
   <div class="line2"><span class="p st-${f.st}" title="${esc((ST[f.st]||'')+'：'+s.path)}"><span dir="ltr">${esc(s.path)}</span></span>${stat}<span class="crumb">${kind}</span>
   <span class="vs"><button data-m="diff" class="${view==='diff'?'on':''}">1列</button><button data-m="split" class="${view==='split'?'on':''}">左右</button>${canView?`<button data-m="file" class="${view==='file'?'on':''}">ファイル全体</button>`:''}</span></div>`;
  head.querySelectorAll('.vs button').forEach(b=>b.onclick=()=>{view=b.dataset.m; LS.set('gt.view',view); show(sel)});
  const body=$('#body'), keepTop=opt.keep?body.scrollTop:0;
  const q=new URLSearchParams({wt:s.wt,f:s.path});
  let html;
  if(view==='file'&&canView){
    if(IMG.test(s.path)) html=`<div class="img"><img src="/api/raw?${q}&t=${Date.now()}"></div>`;
    else{
      const t=await (await fetch('/api/raw?'+q)).text();
      html=MD.test(s.path)&&window.marked?`<div class="md">${marked.parse(t)}</div>`:`<pre class="raw">${esc(t)}</pre>`;
    }
  } else if(IMG.test(s.path)&&canView){
    html=`<div class="img"><img src="/api/raw?${q}&t=${Date.now()}"></div>`;
  } else {
    if(f.untracked) q.set('u','1');
    const d=await (await fetch('/api/diff?'+q)).json();
    html=(view==='split'?diffSplit(d.diff):diffTable(d.diff))+(d.truncated?'<div class="empty">長いので途中で切っています</div>':'');
  }
  if(sel!==s) return;
  body.innerHTML=html;
  const dir=s.path.includes('/')?s.path.slice(0,s.path.lastIndexOf('/')+1):'';
  body.querySelectorAll('.md img').forEach(img=>{
    const src=img.getAttribute('src')||''; if(/^(https?:|data:|\/)/.test(src)) return;
    const parts=[]; for(const p of (dir+decodeURI(src)).split('/')){ if(p==='..') parts.pop(); else if(p&&p!=='.') parts.push(p); }
    img.src='/api/raw?'+new URLSearchParams({wt:s.wt,f:parts.join('/')});
  });
  body.scrollTop=keepTop;
}
function diffSplit(text){
  if(!text||!text.trim()) return '<div class="empty">差分はありません（バイナリか、空ファイルです）</div>';
  let o=0,n=0; const out=[]; let dels=[], adds=[];
  const cell=(no,t,cls)=>no==null?'<td class="n e"></td><td class="c e"></td>':`<td class="n ${cls}">${no}</td><td class="c ${cls}">${t}</td>`;
  const flush=()=>{ const k=Math.max(dels.length,adds.length);
    for(let i=0;i<k;i++){ const d=dels[i], a=adds[i];
      out.push(`<tr>${d?cell(d[0],d[1],'r'):cell(null)}${a?cell(a[0],a[1],'a'):cell(null)}</tr>`); }
    dels=[]; adds=[]; };
  for(const l of text.split('\n')){
    if(/^(diff --git|index |--- |\+\+\+ |new file|deleted file|similarity|rename |old mode|new mode)/.test(l)) continue;
    const m=l.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if(m){ flush(); o=+m[1]; n=+m[2]; out.push(`<tr class="h"><td class="n"></td><td class="c" colspan="3">${esc(l)}</td></tr>`); continue; }
    if(l.startsWith('Binary')){ flush(); out.push('<tr class="h"><td class="n"></td><td class="c" colspan="3">バイナリファイル</td></tr>'); continue; }
    if(l.startsWith('\\')) continue;
    const c=l[0], t=esc(l.slice(1));
    if(c==='-') dels.push([o++,t]);
    else if(c==='+') adds.push([n++,t]);
    else { flush(); out.push(`<tr>${cell(o++,t,'')}${cell(n++,t,'')}</tr>`); }
  }
  flush();
  return `<table class="d s"><colgroup><col style="width:52px"><col><col style="width:52px"><col></colgroup>${out.join('')}</table>`;
}
function diffTable(text){
  if(!text||!text.trim()) return '<div class="empty">差分はありません（バイナリか、空ファイルです）</div>';
  let o=0,n=0; const h=[];
  for(const l of text.split('\n')){
    if(/^(diff --git|index |--- |\+\+\+ |new file|deleted file|similarity|rename |old mode|new mode)/.test(l)) continue;
    const m=l.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if(m){o=+m[1];n=+m[2];h.push(`<tr class="h"><td class="n"></td><td class="n"></td><td class="c">${esc(l)}</td></tr>`);continue}
    if(l.startsWith('Binary')){h.push(`<tr class="h"><td class="n"></td><td class="n"></td><td class="c">バイナリファイル</td></tr>`);continue}
    if(l.startsWith('\\')) continue;
    const c=l[0], t=esc(l.slice(1));
    if(c==='+') h.push(`<tr class="a"><td class="n"></td><td class="n">${n++}</td><td class="c">+${t}</td></tr>`);
    else if(c==='-') h.push(`<tr class="r"><td class="n">${o++}</td><td class="n"></td><td class="c">-${t}</td></tr>`);
    else h.push(`<tr><td class="n">${o++}</td><td class="n">${n++}</td><td class="c"> ${t}</td></tr>`);
  }
  return `<table class="d">${h.join('')}</table>`;
}
function step(dir){
  const rows=[...document.querySelectorAll('.row[data-key]')]; if(!rows.length) return;
  const i=rows.findIndex(r=>r.classList.contains('sel')); rows[Math.max(0,Math.min(rows.length-1,i+dir))]?.click();
}
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT'){ if(e.key==='Escape') e.target.blur(); return; }
  if(e.key==='j'||e.key==='ArrowDown'){step(1);e.preventDefault()}
  if(e.key==='k'||e.key==='ArrowUp'){step(-1);e.preventDefault()}
  if(e.key==='/'){$('#q').focus();e.preventDefault()}
  if(e.key==='r'){RAW='';load()}
});
$('#q').addEventListener('input',render);
$('#seg').querySelectorAll('button').forEach(b=>{
  b.classList.toggle('on',b.dataset.v===filter);
  b.onclick=()=>{filter=b.dataset.v; LS.set('gt.filter',filter); $('#seg').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b)); render();};
});
(()=>{const app=$('#app'),w=LS.get('gt.lw',340); app.style.setProperty('--lw',w+'px');
  $('#drag').onmousedown=e=>{e.preventDefault();const mv=ev=>{const x=Math.max(220,Math.min(800,ev.clientX));app.style.setProperty('--lw',x+'px');LS.set('gt.lw',x)};
  document.addEventListener('mousemove',mv);document.addEventListener('mouseup',()=>document.removeEventListener('mousemove',mv),{once:true})}})();
load();
</script></body></html>
"""

def main():
    argv = sys.argv[1:]
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return
    if "--init" in argv:
        return init_config()
    port = 7801
    if "--port" in argv:
        i = argv.index("--port")
        port = int(argv[i + 1])
        del argv[i:i + 2]
    paths = [a for a in argv if not a.startswith("-")]
    REPOS[:] = load_repos(paths)
    if not REPOS:
        sys.exit("見るリポジトリがありません。git リポジトリの中で実行するか、"
                 "gtree <パス> で指定するか、gtree --init で設定ファイルを作ってください。")
    if "--cli" in argv:
        cli()
    else:
        serve(port)


if __name__ == "__main__":
    main()
