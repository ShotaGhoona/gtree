"""画面からの要求に答える処理。git に書き込むのは stage() と remove_worktree() だけ。"""
import os
import subprocess

from .git import git, repo_root
from .scan import lookup, refresh, safe_target

MAX_DIFF_LINES = 6000


def file_diff(wt, f, untracked, mode=""):
    real, full, info = safe_target(wt, f)
    if real is None:
        return None
    if mode == "stage":  # staged の版 → 今のファイル
        out = git(real, "diff", "--", f)
    elif untracked:
        out = git(real, "diff", "--no-index", "--", "/dev/null", f, ok=(0, 1))
    else:
        out = git(real, "diff", info["mb"] or "HEAD", "--", f)
    lines = out.splitlines()
    return {"diff": "\n".join(lines[:MAX_DIFF_LINES]), "truncated": len(lines) > MAX_DIFF_LINES,
            "base": info["base"], "exists": os.path.isfile(full)}


def read_file(wt, f):
    """worktree の中のファイルの中身。外を指していたり、なければ None。"""
    real, full, _ = safe_target(wt, f)
    if not real or not os.path.isfile(full):
        return None, None
    with open(full, "rb") as fh:
        return full, fh.read()


def list_untracked(wt, d):
    real, _, _ = safe_target(wt, d)
    if real is None:
        return None
    return git(real, "ls-files", "--others", "--exclude-standard", d.rstrip("/") + "/").splitlines()


def stage(wt, files, op):
    """add（staged にする）と reset（外す）。ファイルの中身は変えない。"""
    real, paths = None, []
    for f in files:
        r, _, _ = safe_target(wt, f)
        if r is None or not f or f.startswith("-"):
            return False
        real = r
        paths.append(f)
    if real is None:
        return False
    if op == "add":
        cmd = ["add", "-A", "--", *paths]
    elif op == "unstage":  # restore --staged は未追跡のパスが1つでも混じると全体が失敗するので reset を使う
        cmd = ["reset", "-q", "--", *paths]
    else:
        return False
    return subprocess.run(["git", "-C", real, *cmd], capture_output=True).returncode == 0


def remove_worktrees(wts):
    """「閉じてOK」の worktree を git worktree remove（--force なし）で閉じる。ブランチは消さない。
    消す直前の状態で判定し直す。うまくいかなかったものを {パス: 理由} で返す。"""
    refresh()
    errs = {}
    for wt in wts:
        info = lookup(str(wt))
        if not info or not info["item"].get("closable"):
            errs[wt] = "閉じてOK の worktree ではありません"
            continue
        real = os.path.realpath(wt)
        r = subprocess.run(["git", "-C", repo_root(real), "worktree", "remove", real], capture_output=True, text=True)
        if r.returncode != 0:
            errs[wt] = r.stderr.strip() or "失敗しました"
    refresh()
    return errs
