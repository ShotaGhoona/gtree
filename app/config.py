"""見るリポジトリの決め方（引数 > 設定ファイル > 今いるリポジトリ）。"""
import json
import os
import sys

from .git import repo_root

HOME = os.path.expanduser("~")
CONFIG_PATH = os.path.expanduser(os.environ.get("GTREE_CONFIG", "~/.config/gtree/config.json"))
REPOS = []   # [{"path", "color", "icon"(svg 文字列)}]  起動時に load_repos() で埋める


def short_path(path):
    s = path.replace(HOME, "~")
    if "/scratchpad/" in s:
        s = "…/scratchpad/" + s.split("/scratchpad/")[-1]
    return s


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
