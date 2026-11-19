"""git コマンドを読むだけの小さな関数たち。"""
import os
import re
import subprocess


def git(path, *args, ok=(0,)):
    r = subprocess.run(["git", "-c", "core.quotepath=off", "-C", path, *args],
                       capture_output=True, text=True, errors="replace")
    return r.stdout if r.returncode in ok else ""


def succeeds(path, *args):
    return subprocess.run(["git", "-C", path, *args], capture_output=True).returncode == 0


def repo_root(path):
    """worktree の中から呼ばれても、本体（メインの worktree）のパスを返す。"""
    common = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    if not common:
        return ""
    return os.path.dirname(common) if os.path.basename(common) == ".git" else common


def base_ref(repo):
    """ベースブランチ：origin/HEAD、なければ origin/main / develop / master。"""
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


def stashed_branches(repo):
    """stash はリポジトリ全体で1つ。「On ブランチ:」「WIP on ブランチ:」でどのブランチのものか分かる。"""
    return set(re.findall(r"^stash@\{\d+\}: (?:WIP on|On) ([^:]+):", git(repo, "stash", "list"), re.M))


def ahead_count(path, branch, pr_oid=""):
    """まだ push していないコミットの数。push 先が分からないときは None。
    PR があれば PR の先頭のコミットと比べる（マージ後にリモートのブランチが消えていても分かる）。"""
    if pr_oid and succeeds(path, "cat-file", "-e", pr_oid + "^{commit}"):
        return int(git(path, "rev-list", "--count", f"{pr_oid}..HEAD").strip() or 0)
    for ref in ("@{upstream}", f"refs/remotes/origin/{branch}"):
        if git(path, "rev-parse", "--verify", "-q", ref).strip():
            return int(git(path, "rev-list", "--count", f"{ref}..HEAD").strip() or 0)
    return None
