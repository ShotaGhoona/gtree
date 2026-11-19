"""127.0.0.1 だけで待ち受ける小さな HTTP サーバー。"""
import base64
import json
import mimetypes
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import config, ops, prs
from .scan import refresh

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
# 画面のファイルは決まったものだけ返す
STATIC = {"/web/style.css": "text/css; charset=utf-8"}
STATIC.update({f"/web/js/{n}": "text/javascript; charset=utf-8" for n in os.listdir(os.path.join(WEB, "js"))})
# リポジトリの HTML や SVG を、GTREE とは別のサイトとして動かす（中のスクリプトから staged などを操作させない）
SANDBOX = "sandbox allow-scripts allow-forms allow-popups allow-modals"


def web_file(name):
    with open(os.path.join(WEB, name), "rb") as fh:
        return fh.read()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8", sandbox=False):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if sandbox:
            self.send_header("Content-Security-Policy", SANDBOX)
        self.end_headers()
        self.wfile.write(data)

    def json(self, obj, code=200):
        return self.send(code, json.dumps(obj, ensure_ascii=False))

    def not_found(self):
        return self.send(404, "not found", "text/plain")

    def trusted(self, write=False):
        """別のサイトからの要求（DNS リバインディングや、勝手な POST）を断る。"""
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in hosts:
            return False
        if write:
            if self.headers.get("Origin") not in {"http://" + h for h in hosts}:
                return False
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return False
        return True

    # ---- 書き込み
    def do_POST(self):
        if not self.trusted(write=True):
            return self.send(403, "forbidden", "text/plain")
        path = urlparse(self.path).path
        if path not in ("/api/stage", "/api/wt-remove"):
            return self.not_found()
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(n, 1 << 20)) or b"{}")
            if path == "/api/wt-remove":
                return self.json({"errors": ops.remove_worktrees(body.get("wts") or [])})
            items, op = body["items"], body["op"]  # items: [{wt, f}]
            by_wt = {}
            for it in items:
                by_wt.setdefault(it.get("wt", ""), []).append(it.get("f", ""))
        except (ValueError, KeyError, TypeError, AttributeError):
            return self.send(400, "{}")
        if not all(ops.stage(wt, fs, op) for wt, fs in by_wt.items()):
            return self.send(400, "{}")
        return self.json({"ok": True})

    # ---- 読み取り
    def do_GET(self):
        if not self.trusted():
            return self.send(403, "forbidden", "text/plain")
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/":
            return self.send(200, web_file("index.html"), "text/html; charset=utf-8")
        if u.path in STATIC:
            return self.send(200, web_file(u.path[len("/web/"):]), STATIC[u.path])
        if u.path == "/api/tree":
            if q.get("pr") == "1":
                prs.kick()
            return self.json({"repos": refresh()})
        if u.path == "/api/diff":
            r = ops.file_diff(q.get("wt", ""), q.get("f", ""), q.get("u") == "1", q.get("m", ""))
            return self.json(r) if r else self.send(404, "{}")
        if u.path == "/api/icon":
            svg = next((r["icon"] for r in config.REPOS if os.path.basename(r["path"]) == q.get("r")), "")
            return self.send(200, svg, "image/svg+xml") if svg else self.send(404, "", "text/plain")
        if u.path == "/api/ls":
            r = ops.list_untracked(q.get("wt", ""), q.get("d", ""))
            return self.json(r) if r is not None else self.send(404, "[]")
        if u.path == "/api/raw":
            return self.raw(q.get("wt", ""), q.get("f", ""))
        if u.path.startswith("/raw/"):
            # /raw/<worktree のパスを base64url にしたもの>/<ファイルのパス>
            # パスの形にしておくと、HTML の中の相対パス（style.css や img/a.png）がそのまま読める
            key, _, f = u.path[len("/raw/"):].partition("/")
            try:
                wt = base64.urlsafe_b64decode(key + "=" * (-len(key) % 4)).decode()
            except ValueError:
                return self.not_found()
            return self.raw(wt, unquote(f))
        return self.not_found()

    def raw(self, wt, f):
        full, data = ops.read_file(wt, f)
        if full is None:
            return self.not_found()
        ctype = mimetypes.guess_type(full)[0] or "text/plain; charset=utf-8"
        if ctype.startswith("text/") and "charset" not in ctype:
            ctype += "; charset=utf-8"
        return self.send(200, data, ctype, sandbox=ctype.startswith(("text/html", "image/svg")))


def serve(port, open_browser=True):
    for p in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            break
        except OSError:
            continue
    else:
        sys.exit("空いているポートが見つかりませんでした")
    prs.start([r["path"] for r in config.REPOS])
    url = f"http://127.0.0.1:{p}/"
    print(f"gtree: {url}  （止めるときは Ctrl+C）")
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
