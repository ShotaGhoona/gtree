"""worktree のブランチの PR を gh で読む（gh があるときだけ）。

GitHub への問い合わせは遅い（十数秒）ので、別のスレッドで1分ごとに読んで覚えておき、
collect() は覚えている分を使うだけにする。
"""
import json
import shutil
import subprocess
import threading
import time

GH = shutil.which("gh")
FIELDS = "number,title,state,url,headRefName,isDraft,reviewDecision,headRefOid"
NO_PR_BRANCHES = {"main", "master", "develop", "(detached)"}
MISS_RETRY = 600   # PR が見つからなかったブランチは、10分は聞き直さない

_lock = threading.Lock()
_prs = {}     # repo -> {branch: pr}
_want = {}    # repo -> 見たいブランチの集合（collect() が教える）
_miss = {}    # (repo, branch) -> 見つからなかった時刻
_kick = threading.Event()


def get(repo):
    with _lock:
        return dict(_prs.get(repo, {}))


def want(repo, branches):
    with _lock:
        _want[repo] = set(branches)


def kick():
    """すぐ読み直す（画面で r を押したとき）。"""
    _kick.set()


def start(repo_paths):
    if GH:
        threading.Thread(target=_loop, args=(repo_paths,), daemon=True).start()


def _loop(repo_paths):
    while True:
        with _lock:
            ready = bool(_want)
        if ready:  # 最初の collect() が終わるまでは待つ
            for repo in repo_paths:
                _fetch(repo)
            _kick.wait(60)
            _kick.clear()
        else:
            time.sleep(0.5)


def _gh(repo, *args):
    try:
        r = subprocess.run([GH, "pr", "list", *args], cwd=repo, capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def ci_state(checks):
    """statusCheckRollup を ok / run / fail / "" にまとめる。"""
    if not checks:
        return ""
    st = set()
    for c in checks:
        if c.get("__typename") == "StatusContext":
            st.add({"SUCCESS": "ok", "PENDING": "run", "EXPECTED": "run"}.get(c.get("state"), "fail"))
        elif c.get("status") != "COMPLETED":
            st.add("run")
        else:
            bad = c.get("conclusion") in ("FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE")
            st.add("fail" if bad else "ok")
    return "fail" if "fail" in st else "run" if "run" in st else "ok"


def _fetch(repo):
    with _lock:
        branches = set(_want.get(repo, ()))
    if not branches:
        return
    # 開いている PR（CI 付き）と最近マージされた PR をまとめて読み、残りはブランチごとに聞く
    prs = _gh(repo, "--state", "open", "--limit", "100", "--json", FIELDS + ",statusCheckRollup") + \
        _gh(repo, "--state", "merged", "--limit", "100", "--json", FIELDS)
    now = time.time()
    for b in branches:
        if not any(p["headRefName"] == b for p in prs) and now - _miss.get((repo, b), 0) > MISS_RETRY:
            got = _gh(repo, "--head", b, "--state", "all", "--limit", "5", "--json", FIELDS)
            if got:
                prs += got
            else:
                _miss[(repo, b)] = now
    found = {}
    for p in prs:
        b = p["headRefName"]
        cur = found.get(b)
        # 開いている PR を優先し、その中では新しいもの
        if b in branches and (cur is None or (p["state"] == "OPEN", p["number"]) > (cur["state"] == "OPEN", cur["number"])):
            found[b] = p
    out = {b: {"number": p["number"], "title": p["title"], "url": p["url"], "state": p["state"],
               "draft": p.get("isDraft", False), "review": p.get("reviewDecision") or "",
               "oid": p.get("headRefOid", ""), "ci": ci_state(p.get("statusCheckRollup"))}
           for b, p in found.items()}
    with _lock:
        _prs[repo] = out
