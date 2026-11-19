"""gtree --cli：ターミナルにツリーだけ出す。"""
import os
import sys

from .scan import refresh

COLOR = {"A": "32", "M": "33", "D": "31", "R": "36"}


def cli():
    tty = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    c = (lambda code, s: f"\033[{code}m{s}\033[0m") if tty else (lambda code, s: s)
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
                print(pre + c(COLOR.get(f["st"], "0"), f"{f['st']} {f['path']}") + c("2", extra + tag))
        print()
