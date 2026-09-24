#!/usr/bin/env python3
"""sectest.py —— 安全自测：证明「外部网页隔空调用」和「路径穿越」都进不来。

这几项都是发布前必须过的（同类插件踩过路径穿越）。
每项要么被明确拒绝，要么根本没碰到文件；任何一项漏了就直接报红。
"""
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

B = "http://127.0.0.1:8787"
FAILS = []
TOKEN = None


def page():
    return urllib.request.urlopen(B + "/", timeout=30).read().decode("utf-8", "replace")


def token():
    global TOKEN
    if TOKEN is None:
        m = re.search(r'const TOKEN="([0-9a-f]{32})"', page())
        if not m:
            raise SystemExit("拿不到页面令牌 —— 服务没在跑？")
        TOKEN = m.group(1)
    return TOKEN


def raw(path, body=b"", headers=None, method="POST"):
    """发一个原始请求，返回 (状态码, 正文)。不抛异常，方便断言。"""
    req = urllib.request.Request(B + path, data=body, headers=headers or {}, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # 连接层面的拒绝也算通过（连接被关掉 = 没执行）
        return 0, f"{type(e).__name__}: {e}"


def ok(name, cond, detail=""):
    print(("  OK  " if cond else "  XX  ") + name + (f" —— {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def main():
    print("=== 安全自测：本机服务只该听本页面的，别的一律拒绝 ===\n")
    print("1) 没有令牌的请求")
    st, body = raw("/api/state", json.dumps({}).encode(),
                   {"Content-Type": "application/json"})
    ok("无令牌 POST 被拒", st == 403 and "令牌" in body, f"{st} {body[:60]}")

    print("\n2) 令牌对、但来源是外部网页（带 Origin 头）")
    st, body = raw("/api/state", json.dumps({}).encode(),
                   {"Content-Type": "application/json", "X-MR-Token": token(),
                    "Origin": "https://evil.example.com"})
    ok("外站来源被拒", st == 403 and "来源" in body, f"{st} {body[:60]}")

    print("\n3) 令牌对、来源对、但用表单那种 Content-Type（这就是绕过跨域预检的姿势）")
    st, body = raw("/api/state", json.dumps({}).encode(),
                   {"Content-Type": "text/plain", "X-MR-Token": token(),
                    "Origin": B})
    ok("非 application/json 被拒", st == 415, f"{st} {body[:60]}")

    print("\n4) 超大请求（只声明长度、不真的发 2MB —— 看服务认不认这个门）")
    import socket
    s = socket.create_connection(("127.0.0.1", 8787), timeout=30)
    s.sendall((
        "POST /api/state HTTP/1.1\r\nHost: 127.0.0.1:8787\r\n"
        "Content-Type: application/json\r\n"
        f"X-MR-Token: {token()}\r\nOrigin: {B}\r\n"
        "Content-Length: 2000000\r\nConnection: close\r\n\r\n").encode())
    head = b""
    try:
        while len(head) < 200:
            chunk = s.recv(200)
            if not chunk:
                break
            head += chunk
    except Exception:
        pass
    s.close()
    first = head.decode("utf-8", "replace").split("\r\n")[0]
    ok("超大 body 被拒", "413" in first, first or "(没有响应)")

    print("\n5) 路径穿越：拿 id 当路径用")
    evil = ["../../../../evil", "..%2f..%2fevil", "a/../../b", "C:\\Windows\\win",
            "....//....//x", "", "x" * 200]
    for e in evil:
        for path in ("/api/record/save", "/api/record/approve_one", "/api/undo"):
            st, body = raw(path, json.dumps({"id": e, "log_id": e, "ops": [], "index": 0}).encode(),
                           {"Content-Type": "application/json", "X-MR-Token": token(), "Origin": B})
            try:
                obj = json.loads(body)
            except Exception:
                obj = {}
            good = st in (200, 400, 403, 500) and obj.get("ok") is False
            ok(f"{path} 拒绝 id={e[:14]!r}", good, f"{st} {str(obj.get('error'))[:70]}")

    print("\n6) 快照回退也不能被穿越")
    for e in ["../../evil", "../..", "..%2f..%2fx"]:
        st, body = raw("/api/rollback", json.dumps({"name": e}).encode(),
                       {"Content-Type": "application/json", "X-MR-Token": token(), "Origin": B})
        try:
            obj = json.loads(body)
        except Exception:
            obj = {}
        ok(f"回退拒绝 name={e[:14]!r}", obj.get("ok") is False, f"{st} {str(obj.get('error'))[:70]}")

    print("\n7) 正常的本页面请求必须照常能用（别把自己也拦了）")
    st, body = raw("/api/record/save", json.dumps({"id": "sec00000", "ops": []}).encode(),
                   {"Content-Type": "application/json", "X-MR-Token": token(), "Origin": B})
    try:
        obj = json.loads(body)
    except Exception:
        obj = {}
    err = str(obj.get("error", ""))
    ok("带令牌+同源+json 的请求进了正常流程（不是被门拦住）",
       st == 200 and "不在了" in err, f"{st} {err[:80]}")

    print("\n8) GET 只读：拿不到令牌的网页也读不走内容（同源策略帮忙，但确认没有 CORS 头）")
    req = urllib.request.Request(B + "/api/state", headers={"Origin": "https://evil.example.com"})
    r = urllib.request.urlopen(req, timeout=30)
    acao = r.headers.get("Access-Control-Allow-Origin")
    ok("没有 CORS 放行头", not acao, f"ACAO={acao}")

    print("\n9) 预检（OPTIONS）：本机页面要答应，外站要拒 —— 走了代理/隧道时全靠它")
    import socket as _s

    def options_probe(origin):
        c = _s.create_connection(("127.0.0.1", 8787), timeout=20)
        c.sendall((f"OPTIONS /api/state HTTP/1.1\r\nHost: 127.0.0.1:8787\r\n"
                   f"Origin: {origin}\r\nAccess-Control-Request-Method: POST\r\n"
                   "Access-Control-Request-Headers: x-mr-token\r\nConnection: close\r\n\r\n").encode())
        buf = b""
        try:
            while len(buf) < 400:
                ch = c.recv(400)
                if not ch:
                    break
                buf += ch
        except Exception:
            pass
        c.close()
        return buf.decode("utf-8", "replace")

    mine = options_probe(B)
    ok("本机页面的预检被答应（204 + 允许头）",
       "204" in mine.split("\r\n")[0] and "x-mr-token" in mine.lower(), mine.split("\r\n")[0])
    theirs = options_probe("https://evil.example.com")
    ok("外站页面的预检被拒（403）", "403" in theirs.split("\r\n")[0], theirs.split("\r\n")[0])

    print()
    if FAILS:
        print(f"XX 有 {len(FAILS)} 项没通过：" + "；".join(FAILS))
        return 1
    print("OK 安全自测全部通过：外部网页进不来，路径穿越进不来，本页面照常能用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
