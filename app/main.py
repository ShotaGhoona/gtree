"""gtree: 複数リポジトリ × worktree × フォルダ階層 で差分を見る。

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
をまとめて 1 本のツリーにする。git に書き込むのは staged にする／外す（add / reset）と、
「閉じてOK」の worktree を閉じる（worktree remove）だけ。
"""
import sys

from . import config


def main():
    argv = sys.argv[1:]
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return
    if "--init" in argv:
        return config.init_config()
    port = 7801
    if "--port" in argv:
        i = argv.index("--port")
        port = int(argv[i + 1])
        del argv[i:i + 2]
    config.REPOS[:] = config.load_repos([a for a in argv if not a.startswith("-")])
    if not config.REPOS:
        sys.exit("見るリポジトリがありません。git リポジトリの中で実行するか、"
                 "gtree <パス> で指定するか、gtree --init で設定ファイルを作ってください。")
    if "--cli" in argv:
        from .cli import cli
        cli()
    else:
        from .server import serve
        serve(port, open_browser="--no-open" not in argv)
