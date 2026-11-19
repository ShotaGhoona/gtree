"""全リポジトリ・全 worktree の変更を集める。画面の左のツリーの元になる。"""
import os
import threading

from . import config, prs
from .git import ahead_count, base_ref, git, list_worktrees, numstat, remote_web, stashed_branches
from .ports import assign_ports, dev_ports

_lock = threading.Lock()
_index = {}  # worktree の実パス -> {"mb": merge-base, "base": ベースブランチ, "item": 画面に渡した worktree}


def refresh():
    repos, idx = collect()
    with _lock:
        _index.clear()
        _index.update(idx)
    return repos


def lookup(wt):
    """前回の refresh() で見つけた worktree の情報。知らない worktree なら None。"""
    with _lock:
        return _index.get(os.path.realpath(wt))


def safe_target(wt, f):
    """worktree が既知で、ファイルがその中にあるときだけ (worktree の実パス, ファイルの実パス, 情報) を返す。"""
    real = os.path.realpath(wt)
    info = lookup(real)
    if info is None:
        return None, None, None
    full = os.path.realpath(os.path.join(real, f))
    if full != real and not full.startswith(real + os.sep):
        return None, None, None
    return real, full, info


def collect():
    repos, index, all_wts = [], {}, []
    for conf in config.REPOS:
        repo = conf["path"]
        if not os.path.isdir(repo):
            continue
        base = base_ref(repo)
        known_prs = prs.get(repo)
        stashed = stashed_branches(repo)
        wanted, wts = set(), []
        for i, wt in enumerate(list_worktrees(repo)):
            path = wt["worktree"]
            branch = wt.get("branch", "(detached)").replace("refs/heads/", "")
            item = {"path": path, "short": config.short_path(path), "branch": branch, "main": i == 0,
                    "missing": not os.path.isdir(path), "files": [], "ports": []}
            wts.append(item)
            all_wts.append(item)
            if item["missing"]:
                continue
            if branch not in prs.NO_PR_BRANCHES and branch != base.split("/", 1)[-1]:
                wanted.add(branch)
                item["pr"] = known_prs.get(branch)
            item["stash"] = branch in stashed
            mb = git(path, "merge-base", base, "HEAD").strip() if base else ""
            item["files"] = changed_files(path, mb)
            own = bool(mb) and mb != git(path, "rev-parse", "HEAD").strip()  # このブランチで足したコミットがある
            item["ahead"] = ahead_count(path, branch, (item.get("pr") or {}).get("oid", "")) if own or item.get("pr") else 0
            index[os.path.realpath(path)] = {"mb": mb, "base": base, "item": item}
        prs.want(repo, wanted)
        repos.append({"name": os.path.basename(repo), "base": base, "remote": remote_web(repo),
                      "color": conf["color"], "icon": bool(conf["icon"]), "worktrees": wts})
    assign_ports(all_wts, dev_ports())
    for w in all_wts:
        w["closable"] = closable(w)
    return repos, index


def changed_files(path, mb):
    """未コミットの変更と、ベースブランチから足したコミットの変更を1つにまとめる。

    kind: commit = commit 済みだけ / wip = 未コミットだけ / both = 両方
    sx:   staged の状態。all = 全部 staged 済み、more = staged の後にさらに変更あり
    """
    files = {}
    if mb:
        ns = numstat(path, f"{mb}..HEAD")
        for line in git(path, "diff", "--name-status", f"{mb}..HEAD").splitlines():
            parts = line.split("\t")
            f = parts[-1]
            a, d = ns.get(f, ("", ""))
            files[f] = {"path": f, "st": parts[0][0], "kind": "commit", "add": a, "del": d}
    ns = numstat(path, "HEAD")
    new_dirs = []
    for line in git(path, "status", "--porcelain=v1", "-unormal").splitlines():
        xy, f = line[:2], line[3:]
        if " -> " in f:
            f = f.split(" -> ")[-1]
        f = f.strip('"')
        if xy == "??":
            is_dir = f.endswith("/")
            if is_dir:
                new_dirs.append(f)
            files[f.rstrip("/")] = {"path": f.rstrip("/"), "st": "A", "kind": "wip",
                                    "untracked": True, "dir": is_dir, "add": "", "del": ""}
            continue
        st = (xy.replace(" ", "") or "M")[0]
        a, d = ns.get(f, ("", ""))
        prev = files.get(f)
        sx = "" if xy[0] == " " else ("more" if xy[1] != " " else "all")
        files[f] = {"path": f, "st": prev["st"] if prev and prev["st"] == "A" else st,
                    "kind": "both" if prev else "wip", "add": a, "del": d, "sx": sx}
    for f in new_dirs:  # 新しいフォルダの中身の数
        files[f.rstrip("/")]["count"] = len(git(path, "ls-files", "--others", "--exclude-standard", f).splitlines())
    return sorted(files.values(), key=lambda x: x["path"])


def closable(w):
    """閉じてOK：本体ではない・PR がマージ済み・未コミットの変更なし・push 済み・stash なし・開発サーバー停止。"""
    pr = w.get("pr")
    return bool(not w["main"] and not w["missing"] and pr and pr["state"] == "MERGED"
                and not any(f["kind"] != "commit" for f in w["files"])
                and w.get("ahead") == 0 and not w.get("stash") and not w["ports"])
