#!/usr/bin/env python3
"""server.py —— 「Hermes 记忆工作台」本地页面（只监听 127.0.0.1，不对外开放）。

设计原则：
  · 本文件不 import Hermes 任何代码 —— 只做文件读写和排版（纯规则，无 AI）
  · 所有会碰记忆的动作，都通过 ops.py 新开一个进程去做（见 ops.py 顶部说明）
  · 你删掉这个文件夹，Hermes 一切照旧
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
import i18n                     # 界面/提示文案的中英词典（唯一一份）
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent


def _args():
    import argparse
    CL = i18n.console_lang()
    ap = argparse.ArgumentParser(description=i18n.t("Hermes 记忆工作台 —— 看、改、批、撤 Hermes 的记忆（本地页面）", CL))
    ap.add_argument("--demo", action="store_true",
                    help=i18n.t("用演示数据启动（假档案，跟你的真实记忆完全隔离）", CL))
    ap.add_argument("--demo-reset", action="store_true",
                    help=i18n.t("重建演示数据（配合 --demo）", CL))
    ap.add_argument("--port", type=int, default=int(os.environ.get("MR_PORT", "8787")),
                    help=i18n.t("端口", CL))
    return ap.parse_args()


ARGS = _args()
DEMO = bool(ARGS.demo)
if DEMO:
    import demo as _demo                     # 演示档案：假数据 + 隔离目录
    _demo.ensure_demo_home(reset=bool(ARGS.demo_reset))
    os.environ["MR_HOME"] = str(_demo.DEMO_HOME)
    os.environ["MR_DATA_DIR"] = str(_demo.DEMO_HOME / "data")
    os.environ["MR_PROFILE"] = "default"
os.environ.setdefault("MR_PORT", str(ARGS.port))

DATA_DIR = Path(os.environ.get("MR_DATA_DIR") or TOOL_DIR)   # 动作记录/快照/归档放哪
ROOT = Path(os.environ.get("MR_HOME") or (Path(os.environ.get("LOCALAPPDATA", "")) / "hermes"))
DELIM = "\n§\n"
FILES = {"memory": "MEMORY.md", "user": "USER.md"}
PORT = int(os.environ.get("MR_PORT", "8787"))
DEFAULT_PROFILE = "default"

# ---- 本地服务的三道门 ----
# 只绑 127.0.0.1 是不够的：本机浏览器里打开的**任何网页**都能往这个端口发请求
# （表单 POST 用的 text/plain 属于「简单请求」，绕过了跨域预检），副作用照样发生。
# 所以：① 校验来源 ② 只收 application/json ③ 要求一个只有本页面知道的令牌。
TOKEN = os.urandom(16).hex()
ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
MAX_BODY = 1_000_000


def resolve_lang(accept: str = "") -> str:
    """默认语言：跟随浏览器（Accept-Language 里出现 zh 就是中文，否则英文）。"""
    return i18n.resolve_lang(accept, fallback="zh")


def page_html(accept_lang: str = "") -> str:
    """把令牌 + 中英词典塞进页面再发出去（跨域读不到页面内容，所以外部网页拿不到它们）。

    词典一定要带上：页面右上角那个语言按钮是**页内切换**，不带词典就切不动了
    （中文用户切英文也要靠它）。中文模式下用不到，但只有 10KB，本地页面不值当省。
    """
    ui = {"lang": resolve_lang(accept_lang), "en": i18n.EN}
    return (PAGE.replace("__MR_TOKEN__", TOKEN)
                .replace("__MR_UI__", json.dumps(ui, ensure_ascii=False)))


def safe_rec_id(rec_id: str) -> str:
    """队列编号来自网页请求，必须先校验再当文件名用（否则 `../` 能读写到别处）。"""
    raw = str(rec_id or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", raw):
        label = i18n.t("记录编号", req_lang())          # 标签先按请求语言翻，整句才翻得干净
        raise ValueError(f"{label}不合法：{raw[:40]!r}（只允许字母、数字、- 和 _，64 字以内）")
    return raw


def profiles() -> dict:
    """能看的档案：default（根目录那份）+ profiles/<名字>（每个都是一套独立记忆）。

    每次请求都重新扫一遍 —— 用户中途新建档案（甚至改名），刷新页面就能看见，不用重启服务。
    只要目录里有 memories/ 或 config.yaml 就算一个档案：**刚建好、还没写过记忆的档案也要列出来**，
    否则用户会以为工具没读到他新建的那个。
    """
    out = {}
    if (ROOT / "memories").exists() or (ROOT / "config.yaml").exists():
        out[DEFAULT_PROFILE] = ROOT
    pd = ROOT / "profiles"
    if pd.exists():
        for d in sorted(pd.iterdir()):
            if d.is_dir() and ((d / "memories").exists() or (d / "config.yaml").exists()):
                out[d.name] = d
    return out


def home_of(profile: str) -> Path:
    """档案的「家目录」。Hermes 自己也是靠这个目录定位记忆的。"""
    return profiles().get(profile or DEFAULT_PROFILE) or ROOT


def pending_dir(profile: str) -> Path:
    return home_of(profile) / "pending" / "memory"


def mem_dir(profile: str) -> Path:
    return home_of(profile) / "memories"

PY = sys.executable
_lock = threading.Lock()
_limits_cache = {"at": 0.0, "data": None}


# ---------------- 小工具 ----------------
def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def entries(profile: str, target: str) -> list:
    raw = read(mem_dir(profile) / FILES[target])
    return [e for e in (x.strip() for x in raw.split(DELIM)) if e]


def ops_list(payload: dict) -> list:
    if payload.get("action") == "batch":
        return list(payload.get("operations") or [])
    return [payload]


def op_status(action: str, old: str, cur: str, items: list) -> tuple:
    """这处改动现在还能不能落地 → (能不能, 提示, 级别, 会被覆盖的那一整条原文)。

    匹配规则与 Hermes 源码一致：整条**完全相等**优先，没有才用「包含」；
    命中多条不同的条目 = 歧义（系统会拒）。
    """
    if action not in ("replace", "remove") or not old:
        return ((old in cur) if old else None), "", "", ""
    exact = [e for e in items if e == old]
    hits = exact if exact else [e for e in items if old in e]
    if not hits:
        return False, ("这句旧文已经找不到了（多半被后来的写入换掉过）—— 去「全部记忆」里挑一句现在还在的"
                       if action == "replace" else "这段原文已经不在文件里 —— 批准会失败"), "bad", ""
    if len(set(hits)) > 1:
        return False, "这段旧文能对上好几条不同的记忆 —— 系统无法确定改哪一条，把旧文写成完整的那一条", "bad", ""
    return True, "", "", hits[0]


def records(profile: str) -> list:
    out = []
    pdir = pending_dir(profile)
    if not pdir.exists():
        return out
    for f in sorted(pdir.glob("*.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        payload = rec.get("payload") or {}
        target = payload.get("target", "memory")
        cur = read(mem_dir(profile) / FILES.get(target, "MEMORY.md"))
        items = [e for e in (x.strip() for x in cur.split(DELIM)) if e]
        ops = []
        for op in ops_list(payload):
            act = op.get("action", "?")
            old = (op.get("old_text") or "").strip()
            content = op.get("content") or op.get("new_text") or ""
            hit, note, level, match = op_status(act, old, cur, items)
            ops.append({"action": act, "content": content, "old_text": old,
                        "note": note, "level": level, "match": match})
        out.append({"id": rec.get("id"), "created": rec.get("created_at", 0),
                    "origin": rec.get("origin", ""), "target": target,
                    "summary": rec.get("summary", ""), "ops": ops,
                    "edited": bool(rec.get("edited"))})
    return out


def limits(profile: str) -> dict:
    key = profile or DEFAULT_PROFILE
    if time.time() - _limits_cache["at"] < 20 and _limits_cache["data"] and _limits_cache.get("key") == key:
        return _limits_cache["data"]
    try:
        r = run_ops(["limits"], timeout=60, profile=key)
        data = {"usage": r.get("usage", {}), "limits": r.get("limits", {}), "ok": r.get("ok", False)}
    except Exception as e:  # noqa: BLE001
        data = {"usage": {}, "limits": {}, "ok": False, "error": str(e)}
    _limits_cache.update({"at": time.time(), "data": data, "key": key})
    return data


# 每个请求一个语言（服务是多线程的，所以放 threading.local；同一请求的 ops.py 子进程也读它）
_REQ = threading.local()


def req_lang() -> str:
    return getattr(_REQ, "lang", "zh")


def set_req_lang(accept: str = "", explicit: str = "") -> str:
    lang = explicit if explicit in ("zh", "en") else resolve_lang(accept)
    _REQ.lang = lang
    return lang


def run_ops(argsv: list, timeout: int = 240, profile: str = DEFAULT_PROFILE) -> dict:
    """跑一次 ops.py。HERMES_HOME 决定这是哪个档案的记忆（Hermes 自己也是这么认的）。"""
    env = {**os.environ, "HERMES_HOME": str(home_of(profile)), "MR_PROFILE": profile or DEFAULT_PROFILE,
           "MR_LANG": req_lang()}
    try:
        p = subprocess.run([PY, str(TOOL_DIR / "ops.py"), *argsv], capture_output=True, text=True,
                           encoding="utf-8", timeout=timeout, cwd=str(TOOL_DIR), env=env)
    except FileNotFoundError:
        return {"ok": False, "error": f"找不到 Python（{PY}）—— 用 start.cmd / start.sh 启动它"}
    lines = (p.stdout or "").strip().splitlines()
    if not lines:
        return {"ok": False, "error": (p.stderr or "ops.py 没有任何输出").strip()[:600]}
    try:
        return json.loads(lines[-1])
    except Exception:
        return {"ok": False, "error": f"ops.py 输出无法解析：{lines[-1][:300]}"}


# ---- 启动自检：把「能不能正常读写」在开局就问清楚 ----
HEALTH = {"at": 0.0, "data": None}


def health(refresh: bool = False, profile: str = DEFAULT_PROFILE) -> dict:
    """跑一遍 ops.py selfcheck（读记忆 / 队列 / 沙盒试跑 / 路径可写）。

    结论只用于「告诉你哪里不通」，绝不自己拼记忆文件 —— 不通就是不写。
    """
    if not refresh and HEALTH["data"] and time.time() - HEALTH["at"] < 600:
        return HEALTH["data"]
    r = run_ops(["selfcheck"], timeout=240, profile=profile)
    checks = r.get("checks") or []
    bad = [c for c in checks if not c.get("ok")]
    data = {"ok": bool(checks) and not bad, "checks": checks, "at": time.time(),
            "error": "" if checks else (r.get("error") or "自检没有返回结果")}
    HEALTH.update({"at": time.time(), "data": data})
    return data


def save_record(rec_id: str, ops: list, profile: str) -> dict:
    """把你改过的文字写回队列里的记录（只动队列，不碰记忆）。"""
    try:
        rec_id = safe_rec_id(rec_id)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    p = pending_dir(profile) / f"{rec_id}.json"
    if not p.exists():
        return {"ok": False, "error": "这条记录已经不在了（可能已在别处处理）"}
    rec = json.loads(p.read_text(encoding="utf-8"))
    target = (rec.get("payload") or {}).get("target", "memory")
    clean = [{"action": o.get("action", "replace"), "content": o.get("content", ""),
              "old_text": o.get("old_text", "")} for o in ops]
    if not clean:
        return {"ok": False, "error": "一条都不剩了 —— 用「不要这一处」把它们逐条丢掉"}
    rec["payload"] = ({"action": "batch", "target": target, "operations": clean} if len(clean) > 1
                      else {**clean[0], "target": target})
    rec["edited"] = True
    rec["edited_at"] = time.time()
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


def _is_mine(name: str, profile: str, others: list, kind: str = "") -> bool:
    """这条快照/归档属于哪个档案。

    优先看它**自己记下的档案名**（快照目录里的 `profile.txt`、归档 JSON 里的 `profile`）——
    这样档案改名后，旧的快照/归档照样认得出来；老东西没写档案名时才退回「档案名-」前缀规则。
    """
    owner = ""
    try:
        if kind == "snapshot":
            p = DATA_DIR / "snapshots" / name / "profile.txt"
            if p.exists():
                owner = p.read_text(encoding="utf-8").strip()
        elif kind == "done":
            rec = json.loads((DATA_DIR / "done" / name).read_text(encoding="utf-8"))
            owner = str(rec.get("profile") or (rec.get("record") or {}).get("profile") or "")
    except Exception:  # noqa: BLE001
        owner = ""
    if owner:
        return owner == profile
    if profile == DEFAULT_PROFILE:
        return not any(name.startswith(f"{o}-") for o in others)
    return name.startswith(f"{profile}-")


def write_gate(profile: str):
    """这个档案「改记忆前先问过我」开着吗？读得到就返回 True/False，读不到返回 None。

    只读配置，不写任何东西。空队列引导里要按它来说不同的话。
    """
    try:
        txt = (home_of(profile) / "config.yaml").read_text(encoding="utf-8")
    except OSError:
        return None
    hit = None
    for m in re.finditer(r"^\s*write_approval\s*:\s*(\S+)", txt, re.M):
        hit = m                          # 取最后一次出现，避免注释/旧值干扰
    if not hit:
        return None
    return hit.group(1).strip().strip("\"'").lower() in ("true", "yes", "on", "1")


def profile_list() -> list:
    """档案清单（含各自的待审条数）—— 页面顶部那排页签用它。"""
    return [{"name": n, "home": str(h),
             "queue": len(list((h / "pending" / "memory").glob("*.json")))
             if (h / "pending" / "memory").exists() else 0}
            for n, h in profiles().items()]


def state(profile: str) -> dict:
    profile = profile or DEFAULT_PROFILE
    known = profiles()
    if profile not in known:
        # 正在看的档案被删掉/改名了：**绝不**拿别的档案的记忆冒充它（否则页面写着 A、写的却是 B）
        return {"ok": False, "stale_profile": True, "profile": profile, "profiles": profile_list(),
                "error": f"找不到档案「{profile}」—— 它可能被删除或改名了。已停在这里，没有显示别的档案的记忆。"}
    snap_dir = DATA_DIR / "snapshots"
    done_dir = DATA_DIR / "done"
    others = [n for n in known if n != DEFAULT_PROFILE]
    log = run_ops(["log", "--limit", "60"], timeout=60, profile=profile).get("entries", [])
    log = [e for e in log if (e.get("profile") or DEFAULT_PROFILE) == profile]
    snaps = sorted([p.name for p in snap_dir.glob("*") if p.is_dir()], reverse=True) if snap_dir.exists() else []
    dones = sorted([p.name for p in done_dir.glob("*.json")], reverse=True) if done_dir.exists() else []
    return {"ok": True, "profile": profile,
            "profiles": profile_list(),
            "records": records(profile),
            "memory": {t: entries(profile, t) for t in FILES},
            "limits": limits(profile),
            "log": log[:40],
            "snapshots": [n for n in snaps if _is_mine(n, profile, others, "snapshot")][:20],
            "done": [n for n in dones if _is_mine(n, profile, others, "done")][:20],
            "health": HEALTH["data"],
            "gate": write_gate(profile),
            "demo": DEMO,
            "home": str(home_of(profile))}


# ---------------- HTTP ----------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        obj = i18n.tr_obj(obj, req_lang())      # 响应里会显示给用户的字段按请求语言翻一遍
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text: str):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        set_req_lang(self.headers.get("Accept-Language", ""), (q.get("lang") or [""])[0])
        if self.path in ("/", "/index.html"):
            return self._html(page_html(self.headers.get("Accept-Language", "")))
        if self.path.startswith("/api/state"):
            prof = (q.get("profile") or [DEFAULT_PROFILE])[0]
            with _lock:
                return self._send(state(prof))
        self._send({"ok": False, "error": "not found"}, 404)

    def do_OPTIONS(self):
        """答应「预检」，但只对本机页面答应。

        正常本机直连不会预检；一旦访问路径上有代理/隧道（远程桌面、端口转发、
        云浏览器）预检就来了 —— 不实现 OPTIONS 的话页面会突然变成「HTTP 501」。
        """
        origin = self.headers.get("Origin")
        if origin in ORIGINS:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-MR-Token")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._send({"ok": False, "error": "拒绝：请求来源不是本机页面"}, 403)

    def do_POST(self):
        set_req_lang(self.headers.get("Accept-Language", ""))
        # 三道门（只绑 127.0.0.1 挡不住本机网页隔空调用）
        origin = self.headers.get("Origin")
        if origin and origin not in ORIGINS:
            return self._send({"ok": False, "error": "拒绝：请求来源不是本机页面"}, 403)
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._send({"ok": False, "error": "拒绝：只接受 application/json"}, 415)
        if self.headers.get("X-MR-Token") != TOKEN:
            return self._send({"ok": False, "error": "拒绝：令牌不对（页面可能没刷新，Ctrl+R 一下）"}, 403)
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self._send({"ok": False, "error": "拒绝：请求太大"}, 413)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            data = {}
        if isinstance(data, dict):                     # 页面显式告诉我们要哪种语言
            set_req_lang(self.headers.get("Accept-Language", ""), str(data.get("lang") or ""))
        with _lock:
            try:
                res = self.route(self.path, data)
            except subprocess.TimeoutExpired:
                res = {"ok": False, "error": "操作超时"}
            except Exception as e:  # noqa: BLE001
                res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            if res.get("ok") and self.path in (
                    "/api/record/approve", "/api/record/approve_one", "/api/record/drop",
                    "/api/memory/save", "/api/undo", "/api/rollback", "/api/record/save"):
                _limits_cache["at"] = 0.0   # 刚动过记忆，别让页面再显示旧用量
            self._send(res)

    def route(self, path: str, d: dict) -> dict:
        p = d.get("profile") or DEFAULT_PROFILE
        if p not in profiles():
            # 档案不存在时**绝不**回落到默认档案去动手（页面写着 A、写的却是 B 是能毁数据的）
            return {"ok": False, "stale_profile": True, "profiles": profile_list(),
                    "error": f"找不到档案「{p}」—— 可能被删除或改名了，这一步没有执行任何操作。"}
        if path == "/api/record/save":
            return save_record(d["id"], d.get("ops") or [], p)
        if path == "/api/record/approve":            # 整条
            return run_ops(["apply", d["id"]], profile=p)
        if path == "/api/record/approve_one":        # 只批某一处
            return run_ops(["apply", d["id"], "--index", str(int(d["index"]))], profile=p)
        if path == "/api/record/dryrun":
            args = ["dryrun", d["id"]]
            if d.get("index") is not None:
                args += ["--index", str(int(d["index"]))]
            return run_ops(args, profile=p)
        if path == "/api/record/drop":               # 丢掉某一处 / 整条
            args = ["drop", d["id"]]
            if d.get("index") is not None:
                args += ["--index", str(int(d["index"]))]
            return run_ops(args, profile=p)
        if path == "/api/memory/save":
            return run_ops(["memop", "--target", d.get("target", "memory"),
                            "--action", d.get("action", "replace"),
                            "--content", d.get("content", ""), "--old-text", d.get("old_text", "")],
                           profile=p)
        if path == "/api/undo":
            return run_ops(["undo", d["log_id"]], profile=p)
        if path == "/api/rollback":
            return run_ops(["rollback", d["name"]], profile=p)
        if path == "/api/selfcheck":
            return run_ops(["selfcheck"], timeout=240, profile=p)
        if path == "/api/health":
            return health(refresh=True, profile=p)
        return {"ok": False, "error": f"未知接口 {path}"}


def main():
    cl = i18n.console_lang()          # 终端横幅也跟着系统区域走（海外用户看到英文）

    def say(s, *args, **vars):
        print(i18n.t(s, cl, *args, **vars))

    if DEMO:
        say("★ 演示模式：用的是演示档案（假数据），你的真实记忆不会被碰。")
        say("  演示档案位置：{}", ROOT)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    say("Hermes 记忆工作台已启动：{}", url)
    say("（关掉这个窗口就是关掉它；它不改 Hermes 任何东西）")

    def _selfcheck():
        """开局先自检一次：不通就当场说清楚，别等你去点按钮才发现。"""
        try:
            h = health(refresh=True)
            if h.get("ok"):
                say("启动自检：通过（读记忆 / 队列 / 沙盒试跑 都正常）")
            else:
                say("启动自检：有问题 —— 页面上会红字提示，未修好前不要批准任何提议：")
                for c in (h.get("checks") or []):
                    if not c.get("ok"):
                        print(f"  ✗ {i18n.tr(c.get('name'), cl)}：{i18n.tr(c.get('detail'), cl)}")
                if h.get("error"):
                    print(f"  ✗ {i18n.tr(h['error'], cl)}")
        except Exception as e:  # noqa: BLE001
            say("启动自检失败（不影响页面浏览）：{}", f"{type(e).__name__}: {e}")

    threading.Thread(target=_selfcheck, daemon=True).start()
    if not os.environ.get("MR_NO_BROWSER"):
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        say("已停止。")


PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hermes 记忆工作台</title>
<style>
:root{
  --ink:#22252e; --muted:#6d7280; --line:#e8e3dc; --bg:#faf8f4; --card:#fff;
  --accent:#6b5bd2; --accent-soft:#f0edfd;
  --ok:#2f9e6f; --ok-soft:#eaf7f0; --warn:#c9822f; --warn-soft:#fff6e8; --bad:#cf5348; --bad-soft:#fdeeec;
  --radius:14px;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.65 "Segoe UI","Microsoft YaHei",system-ui,-apple-system,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 20px 90px}
h1{font-size:23px;margin:0 0 4px}
.sub{color:var(--muted);font-size:13.5px;margin-bottom:14px}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:6px}
.tab{border:1px solid var(--line);background:#fff;border-radius:999px;padding:7px 16px;cursor:pointer;
  font-size:14px;transition:.15s}
.tab:hover{border-color:#cfc7bb}
.tab.on{background:var(--accent);border-color:var(--accent);color:#fff}
.tab .n{opacity:.7;font-size:12.5px;margin-left:6px}
.guide{background:#fffdf7;border:1px solid #f0e4cd;border-left:4px solid var(--warn);
  border-radius:10px;padding:10px 14px;font-size:13.5px;color:#6a5a3f;margin:10px 0 16px}
.guide b{color:#4a3f2c}
button{font:inherit;font-size:13.5px;padding:6px 13px;border-radius:9px;border:1px solid var(--line);
  background:#fff;cursor:pointer;transition:.15s;color:var(--ink)}
button:hover{border-color:#cfc7bb;transform:translateY(-1px)}
button:disabled{opacity:.5;cursor:default;transform:none}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button.ok{background:var(--ok);border-color:var(--ok);color:#fff}
button.ghost{background:transparent}
button.danger{color:var(--bad);border-color:#f0d5d2}
button.sm{padding:4px 10px;font-size:12.5px}
h2{font-size:16px;margin:26px 0 10px;display:flex;align-items:center;gap:8px}
h2 .n{color:var(--muted);font-weight:400;font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  margin-bottom:12px;box-shadow:0 1px 2px rgba(34,37,46,.04);overflow:hidden}
.card>header{display:flex;gap:9px;align-items:center;flex-wrap:wrap;
  padding:11px 16px;border-bottom:1px solid var(--line);background:#fdfcfa}
.tag{font-size:12px;padding:1px 9px;border-radius:999px;background:var(--accent-soft);color:var(--accent)}
.tag.auto{background:#f1efea;color:#7a7267}
.tag.bad{background:var(--bad-soft);color:var(--bad)}
.tag.ok{background:var(--ok-soft);color:var(--ok)}
.meta{font-size:12.5px;color:var(--muted)}
.body{padding:14px 16px}
.op{border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-bottom:12px;background:#fff}
.op:last-of-type{margin-bottom:0}
.op.bad{border-color:#f0cfcb;background:#fffbfa}
.ophead{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
.chip{font-size:12px;padding:1px 9px;border-radius:6px;font-weight:600}
.a-add{background:var(--ok-soft);color:#1f7a54}
.a-replace{background:#eef0fb;color:#4a4fa0}
.a-remove{background:var(--bad-soft);color:#b1443c}
.note{font-size:12.5px;color:var(--bad);background:var(--bad-soft);border-radius:8px;padding:6px 10px;margin:6px 0}
.old{background:#fdf1ef;border-radius:9px;padding:8px 11px;font-size:12.5px;color:#7c5a56;
  margin:0 0 9px;white-space:pre-wrap;word-break:break-word}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:820px){.cols{grid-template-columns:1fr}}
.col>label{display:flex;justify-content:space-between;font-size:12px;color:var(--muted);margin-bottom:4px}
textarea{width:100%;min-height:112px;resize:vertical;padding:10px 11px;border-radius:10px;
  border:1px solid var(--line);font:13px/1.6 "Cascadia Mono",Consolas,"Microsoft YaHei",monospace;
  background:#fcfbf9;color:var(--ink)}
textarea:focus{outline:none;border-color:var(--accent);background:#fff}
.sys{min-height:112px;padding:10px 11px;border-radius:10px;background:#f6f5fb;border:1px dashed #d8d3ee;
  font:13px/1.6 "Cascadia Mono",Consolas,"Microsoft YaHei",monospace;
  white-space:pre-wrap;word-break:break-word}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:11px;align-items:center}
.result{font-size:13px;padding:9px 12px;border-radius:9px;margin-top:9px;display:none;line-height:1.6}
.result.show{display:block}
.result.good{background:var(--ok-soft);color:#1f6b4c;border:1px solid #cfeadd}
.result.bad{background:var(--bad-soft);color:#a03b33;border:1px solid #f0d0cc}
.result.info{background:var(--accent-soft);color:#4b3fa8;border:1px solid #ddd7f5}
.empty{color:var(--muted);font-size:14px;padding:16px;background:var(--card);
  border:1px dashed var(--line);border-radius:var(--radius)}
.bar{height:7px;border-radius:99px;background:#efeadf;overflow:hidden;margin:6px 0}
.bar>i{display:block;height:100%;background:var(--ok)}
.bar.warn>i{background:var(--warn)} .bar.bad>i{background:var(--bad)}
.row{display:flex;gap:10px;align-items:center;font-size:13.5px;padding:9px 12px;border:1px solid var(--line);
  border-radius:10px;background:#fff;margin-bottom:7px;flex-wrap:wrap}
.row .prev{flex:1;min-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.logline{font-size:13px;padding:8px 12px;border:1px solid var(--line);border-radius:10px;background:#fff;
  margin-bottom:7px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.logline .d{flex:1;min-width:220px}
.logline.bad{border-color:#f0d0cc;background:#fffbfa}
input[type=text]{font:inherit;font-size:13.5px;padding:7px 11px;border-radius:9px;border:1px solid var(--line);
  background:#fff;min-width:180px}
input[type=text]:focus{outline:none;border-color:var(--accent)}
.tools{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}
.toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);background:#22252e;color:#fff;
  padding:10px 20px;border-radius:999px;font-size:13.5px;opacity:0;transition:.25s;pointer-events:none;z-index:9}
.toast.show{opacity:.95}
.banner{display:none;background:var(--bad-soft);border:1px solid #f0d0cc;color:#a03b33;
  border-radius:10px;padding:10px 14px;font-size:13.5px;margin:10px 0;align-items:center}
.banner.show{display:block}
.notice{display:none;margin:10px 0 0;border-radius:10px;padding:11px 14px;font-size:13.5px;line-height:1.7}
.notice.show{display:block}
.notice.bad{background:var(--bad-soft);border:1px solid #f0d0cc;color:#8f342c}
.notice.info{background:#f2f6ff;border:1px solid #d5e0f5;color:#2f4a7a}
.notice code{background:rgba(0,0,0,.05);padding:1px 5px;border-radius:4px}
.notice ul{margin:6px 0 0 18px;padding:0}
.pbar{display:flex;gap:8px;flex-wrap:wrap;margin:1px 0 12px}
.pbar .p{border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 15px;cursor:pointer;
  font-size:13.5px;transition:.15s}
.pbar .p:hover{border-color:#cfc7bb}
.pbar .p.on{background:var(--accent);border-color:var(--accent);color:#fff}
.pbar .p .n{opacity:.7;font-size:12px;margin-left:6px}
.warnline{font-size:12.5px;color:var(--warn);background:var(--warn-soft);border-radius:9px;
  padding:6px 12px;align-self:center}
body[data-profile]:not([data-profile="default"]){--accent:#0e8f8f;--accent-soft:#e2f5f5}
body[data-profile]:not([data-profile="default"]) .guide{border-left-color:#0e8f8f;background:#f4fbfb;color:#3f5f5f}
.subnav{display:flex;gap:8px;margin:16px 0 10px;flex-wrap:wrap}
.subnav .s{border:1px solid var(--line);background:#fff;border-radius:9px;padding:6px 15px;cursor:pointer;
  font-size:13.5px;transition:.15s}
.subnav .s:hover{border-color:#cfc7bb}
.subnav .s.on{background:var(--ink);border-color:var(--ink);color:#fff}
.subnav .s .n{opacity:.65;font-size:12px;margin-left:6px}
.fixhint{font-size:12.5px;color:var(--warn);background:var(--warn-soft);border-radius:8px;padding:6px 10px;margin:6px 0}
button[disabled]{opacity:.5}
</style></head><body><div class="wrap">
<h1 id="h1">Hermes 记忆工作台</h1>
<button class="ghost sm" id="langbtn" onclick="toggleLang()" style="position:fixed;top:14px;right:18px;z-index:9"></button>
<button class="ghost sm" id="selfbtn" onclick="selfcheck()" style="position:fixed;top:14px;right:104px;z-index:9"></button>
<div class="sub" id="sub">加载中…</div>
<div class="notice" id="notice"></div>
<div class="banner" id="banner"></div>
<div class="pbar" id="pbar"></div>
<div id="lastbar"></div>
<div class="tabs" id="tabs"></div>
<div id="view"></div>
<div class="toast" id="toast"></div>
</div>
<script>
let S=null, view="records", filter="", memTab="memory", profile="default", staleMsg="";
const TOKEN="__MR_TOKEN__";   // 服务启动时生成，只有本页面知道
/* ---------------- 语言层：界面壳的文案走 T() ---------------- */
const UI=__MR_UI__;
let LANG=(()=>{try{return localStorage.getItem("mr_lang")||UI.lang||"zh"}catch(e){return UI.lang||"zh"}})();
const NORM=s=>String(s==null?"":s).replace(/\s+/g," ").trim();
function T(s,vars){
  let o=s;
  if(LANG!=="zh"){const e=UI.en[NORM(s)];if(e!=null)o=e}
  if(vars)o=String(o).replace(/\{(\w+)\}/g,(m,k)=>vars[k]!=null?vars[k]:m);
  return o;
}
function applyLang(){
  document.documentElement.lang=(LANG==="zh")?"zh-CN":"en";
  document.title=T("Hermes 记忆工作台");
  const h=$("#h1");if(h)h.textContent=T("Hermes 记忆工作台");
  const b=$("#langbtn");if(b)b.textContent=(LANG==="zh")?"English":"中文";
  const s=$("#selfbtn");if(s)s.textContent=T("自检");
}
function toggleLang(){
  LANG=(LANG==="zh")?"en":"zh";
  try{localStorage.setItem("mr_lang",LANG)}catch(e){}
  applyLang();
  refresh();          // 整块重取重画：副标题那行也只在 refresh() 里渲染
}   // 服务启动时生成，只有本页面知道（外部网页读不到页面内容）
const $=s=>document.querySelector(s);
function esc(t){return String(t==null?"":t).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]))}
function toast(t){const el=$("#toast");el.textContent=t;el.classList.add("show");
  clearTimeout(el._t);el._t=setTimeout(()=>el.classList.remove("show"),2500)}
//--transform-start--  （test_js_roundtrip.js 直接抓这段代码来跑，标记别删）
function pretty(t){
  return (t||"")
    .replace(/([；。])(?!\n)/g,"$1\n")
    .replace(/([^\n])([★①②③④⑤⑥⑦⑧⑨⑩])/g,"$1\n$2")
    .replace(/\n{2,}/g,"\n").replace(/^\n+|\n+$/g,"");
}
function collapse(t){
  let out="";
  (t||"").replace(/\r/g,"").split("\n").forEach((line,i)=>{
    if(i===0){out=line;return}
    const prev=out.slice(-1);
    if(prev==="；"||prev==="。"||/^[★①②③④⑤⑥⑦⑧⑨⑩]/.test(line)){out+=line;return}
    out+="\n"+line;
  });
  return out;
}
//--transform-end--
function len(t){return [...(t||"")].length}
function showBanner(on,txt){
  const b=$("#banner");if(!b)return;
  if(txt)b.dataset.msg=txt;
  b.innerHTML=`<b>${T('连不上本地服务。')}</b>${b.dataset.msg||T("那个黑窗口可能被关了 —— 重新双击 start.cmd 就好，你改的东西没有丢。")}
    <button class="sm" onclick="refresh()" style="margin-left:8px">${T('重试')}</button>`;
  b.classList.toggle("show",!!on);
}
async function api(path,data){
  let r;
  try{
    r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-MR-Token":TOKEN},
      body:JSON.stringify(Object.assign({profile:profile,lang:LANG},data||{}))});
  }catch(e){
    showBanner(true);
    return {ok:false,error:T("连不上本地服务（没连上就没写入，记忆是安全的）—— 重新双击 start.cmd 再试。")};
  }
  showBanner(false);
  try{return await r.json()}
  catch(e){return {ok:false,error:T("服务返回了看不懂的内容（HTTP ")+r.status+"）"}}
}
function setProfile(p){
  if(p===profile)return;
  profile=p;filter="";view="records";
  staleMsg="";
  document.body.dataset.profile=p;
  toast(T("切到档案 ")+p+T("（读的是它自己的记忆）"));
  refresh();
}
function renderPbar(){
  document.body.dataset.profile=profile;
  const list=(S&&S.profiles)||[];
  const el=$("#pbar");
  if(list.length<2){el.innerHTML="";return}
  el.innerHTML=T('<span class="meta" style="align-self:center">档案：</span>')+
    list.map(p=>`<div class="p ${p.name===profile?"on":""}" onclick="setProfile('${p.name}')">${esc(p.name)}`+
      (p.queue?`<span class="n">${p.queue}${T(' 条待审')}</span>`:"")+`</div>`).join("")+
    (profile==="default"?"":`<span class="warnline">${T('你正在看的是「')}${esc(profile)}${T('」档案的记忆 —— 不是平时聊天那个')}</span>`);
}
async function refresh(){
  try{
    const r=await fetch("/api/state?profile="+encodeURIComponent(profile)+"&lang="+LANG);
    if(!r.ok)throw new Error("HTTP "+r.status);
    S=await r.json();
    if(S.stale_profile){
      // 正在看的档案被删掉/改名了：服务端不会拿别的档案冒充它，页面自动切到第一个能看的档案
      const gone=profile;
      const list=S.profiles||[];
      const first=((list.find(p=>p.name==="default"))||list[0]||{}).name;
      staleMsg=first?`${T('你刚才看的档案「')}${gone}${T('」已经不在了（被删除或改名），已自动切回「')}${first}」。`
                    :`${T('找不到任何档案 —— 检查 Hermes 是不是装在这里、或这个档案是不是被删了。')}`;
      profile=first||profile;
      if(first)return refresh();
      showBanner(true);
      return;
    }
    profile=S.profile||profile;showBanner(false);
  }catch(e){
    showBanner(true);
    if(!S){$("#view").innerHTML=T('<div class="empty">连不上本地服务 —— 请双击 <code>start.cmd</code> 重新启动。</div>');
      $("#tabs").innerHTML="";$("#sub").textContent=T("服务未连接");return}
    toast(T("连不上服务，页面显示的是上一次读到的内容"));
    return;
  }
  renderPbar();
  renderLast();
  const L=S.limits||{};
  const where=S.demo?T("演示档案（假数据，跟你的真实记忆无关）"):S.home;
  $("#sub").textContent=`${T('档案 ')}${profile} ｜ ${where}${T(' ｜ 我的笔记 ')}${(L.usage||{}).memory||"?"}${T(' 字 ｜ 用户画像 ')}${(L.usage||{}).user||"?"}${T(' 字 ｜ 只在本机跑')}`;
  render();
}
function tabs(){
  const bad=S.records.filter(r=>r.ops.some(o=>o.level==="bad")).length;
  $("#tabs").innerHTML=
    `<div class="tab ${view==="records"?"on":""}" onclick="go('records')">${T('待审提议')}<span class="n">${S.records.length}</span></div>`+
    `<div class="tab ${view==="memory"?"on":""}" onclick="go('memory')">${T('全部记忆')}<span class="n">${S.memory.memory.length+S.memory.user.length}${T(' 条')}</span></div>`+
    `<div class="tab ${view==="log"?"on":""}" onclick="go('log')">${T('动作记录')}<span class="n">${S.log.length}</span></div>`+
    (bad?`<div style="align-self:center;color:var(--bad);font-size:13.5px;font-weight:600">${T('⚠ 其中 ')}${bad}${T(' 条含失效项')}</div>`:"");
}
function go(v){view=v;render()}
function render(){tabs();renderNotice();
  if(view==="records")return viewRecords();
  if(view==="memory")return viewMemory();
  return viewLog();}
function renderNotice(){
  const el=$("#notice"); if(!el)return;
  const parts=[]; let bad=false;
  if(staleMsg){parts.push(`<b>⚠ ${esc(staleMsg)}</b>`);bad=true}
  if(S&&S.health&&S.health.ok===false){
    bad=true;
    const list=(S.health.checks||[]).filter(c=>!c.ok);
    parts.push(`<b>${T('⚠ 启动自检没通过 —— 修好之前先别批准任何提议')}</b>
      <div style="margin-top:4px">${T('批准不会硬写：通道不通它会明确报错、记忆保持原样。下面是哪一项不通：')}</div>
      <ul>${list.map(c=>`<li>${esc(c.name)}：${esc(c.detail)}</li>`).join("")}
        ${S.health.error?`<li>${esc(S.health.error)}</li>`:""}</ul>
      <div style="margin-top:6px">${T('改完配置或装好 Hermes 后，点页面右上角的「自检」重新检查一遍。')}</div>`);
  } else if(S&&S.demo){
    parts.push(`<b>${T('演示模式')}</b>${T('：你看到的是一份假档案（假人物、假记忆），\n      批准、改写、撤回随便点，')}<b>${T('你的真实记忆一个字节都不会变')}</b>${T('。\n      想回到自己的记忆：关掉窗口，用 ')}<code>start.cmd</code>${T(' 重新打开。')}`);
  }
  if(S&&S.ok&&!(S.memory&&S.memory.memory||[]).length&&!(S.memory&&S.memory.user||[]).length){
    parts.push(`${T('这个档案（')}<b>${esc(S.profile)}</b>${T('）还没有记忆 —— 多半是刚建好、Hermes 还没往里写过东西。\n      一旦写了，刷新一下这里就会出现。')}`);
  }
  el.className=parts.length?("notice "+(bad?"bad":"info")+" show"):"notice";
  el.innerHTML=parts.join("<hr style='border:none;border-top:1px solid rgba(0,0,0,.08);margin:8px 0'>");
}
function usageBar(t){
  const u=(S.limits.usage||{})[t]||"0 / 0", L=(S.limits.limits||{})[t]||0;
  const used=parseInt(String(u).split("/")[0].replace(/[^0-9]/g,""),10)||0;
  const pct=L?Math.round(used/L*100):0;
  const cls=pct>97?"bad":pct>88?"warn":"";
  return `<div class="bar ${cls}"><i style="width:${Math.min(pct,100)}%"></i></div>
    <span class="meta">${T('用了 ')}${used} / ${L}${T(' 字（')}${pct}%）</span>`;
}
/* ---------------- 视图一：待审提议 ---------------- */
function emptyGuide(){
  const g=S.gate;
  const gate = g===true
    ? `${T('写入需批准：')}<b style="color:#2c7a4b">${T('已开启')}</b>${T(' —— 系统想改记忆时会先来这里排队等你点头。')}`
    : g===false
      ? `${T('写入需批准：')}<b style="color:#a03b33">${T('还没开')}</b>${T(' —— 没开的话系统会直接改记忆、不问你。')}<br>${T('\n         想开：在聊天里输入 ')}<code>/memory approval on</code>${T('（写在哪个档案就管哪个档案）。')}`
      : `${T('写入需批准：')}<b>${T('读不到配置')}</b>${T(' —— 检查这个档案 ')}<code>config.yaml</code>${T(' 里的 ')}<code>memory.write_approval</code>。`;
  return `<div class="empty" style="padding:20px;line-height:1.95">
    <b style="font-size:15px">${T('队列是空的 —— 这是正常状态')}</b><br>${T('\n    只有「系统想改记忆」和「写入需批准已开」两件事同时成立，这里才会有东西。')}<br>
    <div style="margin-top:6px">${gate}</div>
    <div style="margin-top:12px"><b>${T('想马上看它工作起来：')}</b>
      <ol style="margin:6px 0 0 18px;padding:0">
        <li>${T('回到聊天，让 Hermes 记住一件事（比如「记住我对花生过敏」）')}</li>
        <li>${T('它想记的时候会被拦住 —— 这里就会出现一条待审提议')}</li>
        <li>${T('回来批准 / 改写 / 丢弃；想反悔就点撤回，记忆能回到原样')}</li>
      </ol></div>
    <div style="margin-top:12px;color:var(--muted)">${T('\n      想先看它长什么样：')}<code>python server.py --demo</code>${T('（假档案，跟你的真实记忆完全隔离）\n      —— 也可以点上面的「自检」按钮看这台机器的读写通道通不通。\n    ')}</div>
  </div>`;
}
function viewRecords(){
  const v=$("#view");
  if(!S.records.length){v.innerHTML=emptyGuide();return}
  v.innerHTML=`<div class="guide">
    <b>${T('一个 ID 里可能有好几处改动，可以分开处理。')}</b>${T('想一次全批就点卡片底部的「全部批准」；\n    只想批其中一处，就点那一处自己的「批准这一处」。\n    ')}<b>${T('改文字')}</b>${T('：直接在左边的框里打字，右边是真正写进系统的那一行（跟着变、字数实时）；\n    改完可以点「保存草稿」，也可以直接点「批准」（会先存再批）。\n    ')}<b>${T('只有「批准」会写进 MEMORY.md / USER.md')}</b>${T('，其余动作只动队列。\n  ')}</div>`;
  for(const r of S.records){
    const tgt=r.target==="user"?T("用户画像 USER.md"):T("我的笔记 MEMORY.md");
    const bad=r.ops.filter(o=>o.level==="bad").length;
    const el=document.createElement("div");el.className="card";
    el.innerHTML=`<header>
        <code style="color:var(--accent);font-weight:600">${r.id}</code>
        <span class="meta">${new Date(r.created*1000).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"})}</span>
        <span class="tag">${tgt}</span>
        <span class="tag ${r.origin==="background_review"?"auto":""}">${r.origin==="background_review"?T("后台复盘"):T("我（聊天中）")}</span>
        <span class="meta">${r.ops.length}${T(' 处改动')}</span>
        ${bad?`<span class="tag bad">${bad}${T(' 处现在落不了地')}</span>`:`<span class="tag ok">${T('都能落地')}</span>`}
        ${r.edited?`<span class="tag auto">${T('你已改过')}</span>`:""}
      </header><div class="body" data-rec="${r.id}"></div>`;
    v.appendChild(el);
    const body=el.querySelector(".body");
    r.ops.forEach((o,i)=>{
      const d=document.createElement("div");
      d.className="op "+(o.level==="bad"?"bad":"");
      const label={add:T("新增一条"),replace:T("整条替换"),remove:T("删掉整条")}[o.action]||o.action;
      const isSwap=o.action==="replace"||o.action==="remove";
      const matchBox = (isSwap&&o.match)
        ? `<div class="old"><b>${o.action==="replace"?T("这一整条会被新内容覆盖"):T("这一整条会被删掉")}</b>
             <span class="meta">${T('（旧文只用来找到它，不是改那几个字）：')}</span><br>${esc(o.match)}</div>`
        : (o.old_text?`<div class="old">${T('现在文件里是：')}${esc(o.old_text)}</div>`:"");
      const swapHint = (isSwap&&o.match&&o.match!==o.old_text)
        ? `<div class="note">${T('⚠️ 这是')}<b>${T('整条替换')}</b>${T('：写进去的是左边框里的完整内容，\n             「')}${esc(o.old_text)}${T('」只负责定位。上面那一条里其余的文字会一起消失 —— 想留住它们，就把它们补进左边的框里。')}</div>`
        : "";
      d.innerHTML=`<div class="ophead"><b style="font-size:13px">${T('第 ')}${i+1}${T(' 处')}</b>
          <span class="chip a-${o.action}">${label}</span></div>
        ${o.note?`<div class="note">⚠️ ${esc(o.note)}</div>
          <div class="fixhint">${T('这处落不了地，原因就是上面那条。「批准」已经先关掉了，所以你点不出错。\n            你可以：① 点「不要这一处」把它丢掉；② 真想改这条 —— 点卡片下方的\n            「复制给 Hermes 的指令」发给我，我帮你把「旧文」换成现在文件里真正的那句。')}</div>`:" "}
        ${matchBox}${swapHint}
        <div class="cols">
          <div class="col"><label><span>${T('给我看 / 在这里改')}</span><span class="cnt"></span></label>
            <textarea data-i="${i}"></textarea></div>
          <div class="col"><label><span>${T('真正写进系统的那一行（只读）')}</span></label>
            <div class="sys"></div></div>
        </div>
        <div class="actions">
          <button class="ok" data-approve-one ${o.level==="bad"?`disabled title="${T('这处现在落不了地 —— 看上面的原因')}"`:""}>${T('批准这一处（写进记忆）')}</button>
          <button class="ghost" data-dry>${T('试跑这一处')}</button>
          <button class="ghost danger" data-drop>${T('不要这一处')}</button>
        </div>
        <div class="result"></div>`;
      body.appendChild(d);
      const ta=d.querySelector("textarea"),sys=d.querySelector(".sys"),cnt=d.querySelector(".cnt");
      ta.value=pretty(o.content);
      const sync=()=>{const c=collapse(ta.value);sys.textContent=c;cnt.textContent=`${len(c)}${T(' 字')}`};
      ta.addEventListener("input",sync);sync();
      d.querySelector("[data-approve-one]").onclick=ev=>approveOne(r.id,i,ev.target,d);
      d.querySelector("[data-dry]").onclick=ev=>dryrun(r.id,i,ev.target,d);
      d.querySelector("[data-drop]").onclick=ev=>dropOne(r.id,i,ev.target,d);
    });
    const act=document.createElement("div");act.className="actions";
    act.style.marginTop="14px";act.style.paddingTop="12px";act.style.borderTop="1px dashed var(--line)";
    act.innerHTML=`<button class="primary" data-all ${bad?`disabled title="${T('有失效项 —— 整条一起批会失败，先逐处处理')}"`:""}>${T('全部批准（')}${r.ops.length}${T(' 处一起写进）')}</button>
      <button data-save>${T('保存草稿（先不写）')}</button>
      <button class="ghost" data-copy>${T('复制给 Hermes 的指令')}</button>
      <button class="ghost danger" data-dropall>${T('整条都不要')}</button>`;
    body.appendChild(act);
    const res=document.createElement("div");res.className="result";res.dataset.recres=r.id;
    body.appendChild(res);
    act.querySelector("[data-all]").onclick=ev=>approveAll(r.id,ev.target,res);
    act.querySelector("[data-save]").onclick=ev=>saveDraft(r.id,ev.target,res);
    act.querySelector("[data-copy]").onclick=()=>copyForHermes(r.id);
    act.querySelector("[data-dropall]").onclick=ev=>dropAll(r.id,ev.target);
  }
}
function recCard(id){return document.querySelector(`[data-rec="${id}"]`)?.closest(".card")||null}
function collect(id){
  const card=recCard(id), rec=S.records.find(r=>r.id===id);
  // 页面上的卡片和队列对不上（比如这条刚在别处被处理过）→ 刷新并说清，绝不静默失败
  if(!card||!rec){toast(T("这条已经不在队列里了 —— 页面正在刷新"));refresh();return null}
  const ops=rec.ops.map(o=>({action:o.action,content:o.content,old_text:o.old_text}));
  card.querySelectorAll(".op").forEach((d,i)=>{ops[i].content=collapse(d.querySelector("textarea").value)});
  return ops;
}
function outAt(el,html,cls,keep){
  if(el){el.className="result show "+(cls||"info");el.innerHTML=html}
  // keep=true 的消息（动了记忆的操作）会同时在顶部留一份，页面刷新后也看得到
  if(keep)setLast(html,cls);
}
let lastMsg=null;
function setLast(html,cls){lastMsg={html:html,cls:cls||"good"};renderLast()}
function renderLast(){
  const el=$("#lastbar");if(!el)return;
  el.innerHTML=lastMsg?`<div class="result ${lastMsg.cls} show">${lastMsg.html}</div>`:"";
}
function busy(btn,on){
  if(!btn)return;
  btn.disabled=on;
  if(on){btn._t=btn.textContent;btn.textContent="…";
    // 兜底：15 秒后一定要把按钮恢复，绝不允许"点了没反应、按钮永远转圈"
    clearTimeout(btn._w);btn._w=setTimeout(()=>busy(btn,false),15000);
  } else {clearTimeout(btn._w);if(btn._t)btn.textContent=btn._t}
}
// 任何没被接住的错误都要看得见，并且把卡住的按钮放回来
window.addEventListener("error",ev=>{
  toast(T("出错了：")+(ev.message||T("未知错误")));
  document.querySelectorAll("button[disabled]").forEach(b=>busy(b,false));
});
window.addEventListener("unhandledrejection",ev=>{
  const m=(ev.reason&&ev.reason.message)||ev.reason||T("未知错误");
  toast(T("出错了：")+m);
  document.querySelectorAll("button[disabled]").forEach(b=>busy(b,false));
});
async function saveDraft(id,btn,resEl){
  busy(btn,true);
  const ops=collect(id); if(!ops){busy(btn,false);return}
  const r=await api("/api/record/save",{id,ops});
  busy(btn,false);
  if(resEl)outAt(resEl,r.ok?T("草稿已保存 —— 还没写进记忆（记忆一个字没动）"):T("保存失败：")+esc(r.error||""),r.ok?"info":"bad",true);
  toast(r.ok?T("草稿已保存（记忆没动）"):T("保存失败：不写就什么都不影响"));
  if(r.ok)refresh();
}
async function dryrun(id,index,btn,opEl){
  const out=opEl.querySelector(".result");
  busy(btn,true);
  const ops=collect(id); if(!ops){busy(btn,false);return}
  const s=await api("/api/record/save",{id,ops});
  if(!s.ok){busy(btn,false);outAt(out,T("保存失败：")+esc(s.error||""),"bad");return}
  outAt(out,T("试跑中…"),"info");
  const d=await api("/api/record/dryrun",{id,index});
  busy(btn,false);
  if(d.ok){
    const which=(d.after.memory!==d.before.memory?T("我的笔记"):T("用户画像"));
    const key=(d.after.memory!==d.before.memory?"memory":"user");
    outAt(out,`${T('试跑通过 ✅ 这一处写进去后，')}${which}${T(' 会从 ')}<b>${esc(d.before[key])}</b>${T(' 变成 ')}<b>${esc(d.after[key])}</b>${T('（不写入，只是预演）')}`
      +(d.lost_entry?`<div style="margin-top:6px">${T('这一步会把这一整条覆盖掉：')}<br><b>${esc(d.lost_entry)}</b></div>`:""),"good");
  } else outAt(out,`${T('试跑不通过 ❌ ')}${esc(d.error||"")}<br>${T('记忆没有被改动。')}`,"bad");
}
async function approveOne(id,index,btn,opEl){
  const out=opEl.querySelector(".result");
  busy(btn,true);
  const ops=collect(id); if(!ops){busy(btn,false);return}
  const s=await api("/api/record/save",{id,ops});
  if(!s.ok){busy(btn,false);outAt(out,T("保存失败：")+esc(s.error||""),"bad");return}
  const a=await api("/api/record/approve_one",{id,index});
  busy(btn,false);
  if(a.ok){
    const k=(a.target==="user")?"user":"memory";
    outAt(out,`${T('已写进记忆 ✅ ')}${esc(a.desc||"")}<br>
      ${k==="user"?T("用户画像"):T("我的笔记")}${T('字数：')}<b>${esc((a.before||{})[k])} → ${esc((a.after||{})[k])}</b>
      ｜ ${esc(a.state||"")}<br>${T('\n      不满意就去「动作记录」点「撤回这一步」，只会还原这一处。')}`,"good",true);
    toast(T("已写进记忆 ✅"));
    refresh();
  } else {
    outAt(out,`${T('没有写入 —— 记忆一个字都没动 ❌')}<br>${esc(a.error||"")}`,"bad",true);
    toast(T("没写进去，记忆是安全的"));
  }
}
async function dropOne(id,index,btn,opEl){
  const out=opEl.querySelector(".result");
  if(!confirm(T("丢掉第 ")+(index+1)+T(" 处？\n（不写进记忆，会收进「已完成」留档）")))return;
  busy(btn,true);
  const r=await api("/api/record/drop",{id,index});
  busy(btn,false);
  if(r.ok){outAt(out,T("已丢掉这一处（记忆没动）"),"info");toast(T("已丢掉"));refresh()}
  else outAt(out,T("失败：")+esc(r.error||""),"bad");
}
async function approveAll(id,btn,resEl){
  busy(btn,true);
  const ops=collect(id); if(!ops){busy(btn,false);return}
  const s=await api("/api/record/save",{id,ops});
  if(!s.ok){busy(btn,false);outAt(resEl,T("保存失败：")+esc(s.error||""),"bad");return}
  const a=await api("/api/record/approve",{id});
  busy(btn,false);
  if(a.ok){outAt(resEl,`${T('整条已写进记忆 ✅ ')}${esc(a.state||"")}<br>${T('不满意就去「动作记录」点「撤回这一步」。')}`,"good",true);
    toast(T("已写进记忆 ✅"));refresh()}
  else outAt(resEl,`${T('没有写入 —— 记忆一个字都没动 ❌ ')}${esc(a.error||"")}`,"bad",true);
}
async function dropAll(id,btn){
  if(!confirm(T("整条都不要？\n（不写进记忆，会收进「已完成」留档）")))return;
  busy(btn,true);
  const r=await api("/api/record/drop",{id});
  busy(btn,false);
  toast(r.ok?T("已收进「已完成」"):T("失败：")+r.error);if(r.ok)refresh();
}
function copyForHermes(id){
  const r=S.records.find(x=>x.id===id),ops=collect(id);
  if(!ops)return;
  const lines=ops.map((o,i)=>`${T('第 ')}${i+1}${T(' 处（')}${o.action}${T('）：改成 ')}${o.content}`).join("\n");
  const text=`${T('帮我改待审提议 ')}${id}（${r.target==="user"?T("用户画像"):T("我的笔记")}）：\n${lines}`;
  // 剪贴板在某些环境会被拦，所以再把原文显示出来给她手动选中复制
  const res=document.querySelector(`[data-recres="${id}"]`);
  if(res)outAt(res,`${T('把下面这段发给我（Hermes）就行：\n    ')}<textarea readonly style="min-height:74px;margin-top:6px">${esc(text)}</textarea>`,"info");
  const ta=res&&res.querySelector("textarea");if(ta){ta.focus();ta.select()}
  if(navigator.clipboard&&navigator.clipboard.writeText)
    navigator.clipboard.writeText(text).then(()=>toast(T("已复制，粘到聊天里发给我就行")),
      ()=>toast(T("已显示在卡片上 —— 手动选中复制也行")));
}
/* ---------------- 视图二：全部记忆（整体查看与编辑入口） ---------------- */
function viewMemory(){
  const v=$("#view");
  const n={memory:(S.memory.memory||[]).length,user:(S.memory.user||[]).length};
  v.innerHTML=`<div class="guide">
    <b>${T('这里是现在全部的记忆，这是唯一的编辑入口。')}</b>${T('用下面两个页签在「我的笔记」和「用户画像」之间切换；\n    点某一条的「展开改」就能改，右边实时显示真正写进系统的那一行，保存后立刻生效。\n    改前自动存旧版，不满意就去「动作记录」点「撤回」。\n  ')}</div>
  <div class="subnav">
    ${["memory","user"].map(t=>`<div class="s ${memTab===t?"on":""}" onclick="memTab='${t}';render()">${
      t==="user"?T("用户画像 USER.md"):T("我的笔记 MEMORY.md")}<span class="n">${n[t]}${T(' 条')}</span></div>`).join("")}
  </div>
  <div class="tools">
    <input type="text" id="q" placeholder="${T('在「')}${memTab==="user"?T("用户画像"):T("我的笔记")}${T('」里搜字…')}" value="${esc(filter)}">
    <button onclick="applyFilter()">${T('搜索')}</button>
    <button class="ghost" onclick="filter='';render()">${T('清空')}</button>
  </div>`;
  { const t=memTab;
    const title=t==="user"?T("用户画像 USER.md"):T("我的笔记 MEMORY.md");
    const list=(S.memory[t]||[]);
    const shown=list.map((e,i)=>({e,i})).filter(x=>!filter||x.e.includes(filter));
    const h=document.createElement("h2");
    h.innerHTML=`${title} <span class="n">${list.length}${T(' 条')}${filter?`${T('，匹配 ')}${shown.length}${T(' 条')}`:""}</span>`;
    v.appendChild(h);
    const bar=document.createElement("div");bar.innerHTML=usageBar(t);v.appendChild(bar);
    const add=document.createElement("div");add.className="tools";
    add.innerHTML=`<button class="ghost" data-add>${T('+ 在末尾新增一条')}</button>`;
    v.appendChild(add);
    add.querySelector("[data-add]").onclick=ev=>openAdd(t,ev.target);
    for(const {e,i} of shown){
      const el=document.createElement("div");el.className="row";
      el.innerHTML=`<span class="meta" style="width:38px">${i+1}</span>
        <span class="prev">${esc(e.slice(0,70))}${e.length>70?"…":""}</span>
        <span class="meta">${len(e)}${T(' 字')}</span>
        <button class="sm" data-open>${T('展开改')}</button>`;
      v.appendChild(el);
      const box=document.createElement("div");box.style.display="none";
      v.appendChild(box);
      el.querySelector("[data-open]").onclick=()=>toggleEntry(box,el,t,e);
    }
  }
}
function applyFilter(){filter=$("#q").value.trim();render()}
function toggleEntry(box,row,t,text){
  if(box.style.display!=="none"){box.style.display="none";row.querySelector("[data-open]").textContent=T("展开改");return}
  row.querySelector("[data-open]").textContent=T("收起");
  box.style.display="";
  if(box.dataset.built)return;
  box.dataset.built="1";
  const el=document.createElement("div");el.className="card";
  el.innerHTML=`<div class="body">
    <div class="cols">
      <div class="col"><label><span>${T('给我看 / 在这里改')}</span><span class="cnt"></span></label><textarea></textarea></div>
      <div class="col"><label><span>${T('真正写进系统的那一行（只读）')}</span></label><div class="sys"></div></div>
    </div>
    <div class="actions">
      <button class="ok" data-save>${T('保存这条（立刻生效）')}</button>
      <button class="ghost" data-undo>${T('撤回这份文件最近一次改动')}</button>
      <button class="ghost danger" data-del>${T('删掉这条')}</button>
    </div>
    <div class="result"></div></div>`;
  box.appendChild(el);
  const ta=el.querySelector("textarea"),sys=el.querySelector(".sys"),cnt=el.querySelector(".cnt");
  ta.value=pretty(text);
  const sync=()=>{const c=collapse(ta.value);sys.textContent=c;cnt.textContent=`${len(c)}${T(' 字')}`};
  ta.addEventListener("input",sync);sync();
  const out=el.querySelector(".result");
  el.querySelector("[data-save]").onclick=async ev=>{
    const c=collapse(ta.value);
    if(c===text){outAt(out,T("和现在一模一样，不用保存"),"info");return}
    if(!c){outAt(out,T("不能存成空的 —— 想删掉这条请用「删掉这条」"),"bad");return}
    if(!confirm(T("保存后立刻写进记忆（改前会自动存旧版）。确定？")))return;
    busy(ev.target,true);
    const r=await api("/api/memory/save",{target:t,action:"replace",content:c,old_text:text});
    busy(ev.target,false);
    if(r.ok){
      outAt(out,`${T('已保存 ✅ ')}${t==="user"?T("用户画像"):T("我的笔记")}${T('字数\n        ')}<b>${esc((r.before||{})[t])} → ${esc((r.after||{})[t])}</b>（${r.delta>0?"+":""}${r.delta}）
        <br>${T('不满意点下面的「改回我刚保存前的样子」，或去「动作记录」撤回。')}`,"good",true);
      toast(T("已保存 ✅"));
      text=c;ta.value=pretty(c);sync();
      el.querySelector("[data-undo]").dataset.log=r.log_id||"";
      refresh();
    } else outAt(out,`${T('没有保存 ❌ ')}${esc(r.error||"")}<br>${T('（这句旧文可能已被别处改过 —— 重新展开这条再试）')}`,"bad");
  };
  el.querySelector("[data-del]").onclick=async ev=>{
    if(!confirm(T("确定删掉这条？\n\n")+text.slice(0,60)+"…"))return;
    busy(ev.target,true);
    const r=await api("/api/memory/save",{target:t,action:"remove",content:"",old_text:text});
    busy(ev.target,false);
    if(r.ok){outAt(out,T("已删除 ✅ 可去「动作记录」撤回"),"good",true);toast(T("已删除"));refresh()}
    else outAt(out,`${T('没有删除 ❌ ')}${esc(r.error||"")}`,"bad",true);
  };
  el.querySelector("[data-undo]").onclick=async ev=>{
    let id=ev.target.dataset.log;
    if(!id){
      // 保存后页面会刷新一次，按钮上记的编号会丢 —— 那就退回「这份文件上最近一次写入」
      const last=(S.log||[]).find(e=>e.kind==="memop"&&e.target===t&&e.inverse);
      if(last&&!confirm(T("撤回我在这份文件上最近一次改动？\n\n")+(last.desc||"")))return;
      id=last&&last.log_id;
    }
    if(!id){outAt(out,T("这份文件最近没有可撤回的改动"),"info");return}
    const r=await api("/api/undo",{log_id:id});
    outAt(out,r.ok?(T("已撤回 ✅ 现在是 ")+esc((r.after||{})[t])
        +(r.hardened?T("<div style=\"margin-top:6px\">这一步是较早记录的改动，撤回时按当时那份快照把<b>被覆盖的那一整条</b>补了回来（不会只剩旧文那几个字）。</div>"):""))
      :(T("撤回失败：")+esc(r.error||"")),
      r.ok?"good":"bad",true);
    if(r.ok)refresh();
  };
}
function openAdd(t,btn){
  const box=document.createElement("div");
  box.innerHTML=`<div class="card"><div class="body">
    <div class="cols">
      <div class="col"><label><span>${T('新的一条（给我看 / 在这里写）')}</span><span class="cnt"></span></label>
        <textarea style="min-height:90px"></textarea></div>
      <div class="col"><label><span>${T('真正写进系统的那一行（只读）')}</span></label><div class="sys"></div></div>
    </div>
    <div class="actions"><button class="ok" data-ok>${T('加进去（立刻生效）')}</button>
      <button class="ghost" data-cancel>${T('取消')}</button></div>
    <div class="result"></div></div></div>`;
  btn.closest(".tools").after(box);
  const ta=box.querySelector("textarea"),sys=box.querySelector(".sys"),cnt=box.querySelector(".cnt");
  const sync=()=>{const c=collapse(ta.value);sys.textContent=c;cnt.textContent=`${len(c)}${T(' 字')}`};
  ta.addEventListener("input",sync);sync();
  const out=box.querySelector(".result");
  box.querySelector("[data-cancel]").onclick=()=>box.remove();
  box.querySelector("[data-ok]").onclick=async ev=>{
    const c=collapse(ta.value);
    if(!c){outAt(out,T("先写点内容"),"bad");return}
    busy(ev.target,true);
    const r=await api("/api/memory/save",{target:t,action:"add",content:c,old_text:""});
    busy(ev.target,false);
    if(r.ok){outAt(out,`${T('已加进去 ✅ 现在 ')}${esc((r.after||{})[t]||"")}`,"good",true);toast(T("已加进去"));refresh();setTimeout(()=>box.remove(),600)}
    else outAt(out,`${T('没有加进去 ❌ ')}${esc(r.error||"")}`,"bad");
  };
  ta.focus();
}
/* ---------------- 视图三：动作记录（每一步都能撤回） ---------------- */
function viewLog(){
  const v=$("#view");
  v.innerHTML=`<div class="guide">
    <b>${T('每一次写进记忆的动作都记在这里')}</b>${T('，带字数变化。点「撤回这一步」就精确还原那一步 ——\n    只动它碰过的那条，不影响你之后做的其他改动。\n  ')}</div>`;
  if(!S.log.length){v.innerHTML+=`<div class="empty">${T('还没有动作。做过一次批准/保存后，这里就有记录。')}</div>`;return}
  for(const e of S.log){
    const when=new Date(e.ts*1000).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"});
    const isFail=(e.kind==="fail");
    const tgt=e.target==="user"?T("用户画像"):T("我的笔记");
    const d=document.createElement("div");
    d.className="logline"+(isFail?" bad":"");
    d.innerHTML=`<span class="meta" style="width:82px">${when}</span>
      <span class="d">${isFail?"❌ ":e.kind==="undo"?"↩️ ":e.kind==="drop"?"🗑 ":"✅ "}${esc(e.desc||e.kind)}
        ${e.error?`<span class="meta">— ${esc(e.error)}</span>`:""}</span>
      <span class="meta">${e.before||e.after?`${esc(e.before||"")} → ${esc(e.after||"")}`:esc(tgt)}</span>
      ${e.inverse?`<button class="sm ghost" data-undo>${T('撤回这一步')}</button>`:""}`;
    v.appendChild(d);
    const ub=d.querySelector("[data-undo]");
    if(ub)ub.onclick=async ev=>{
      if(!confirm(T("撤回这一步：「")+(e.desc||"")+T("」？\n只还原这一步，其他改动不受影响。")))return;
      busy(ev.target,true);
      const r=await api("/api/undo",{log_id:e.log_id});
      busy(ev.target,false);
      toast(r.ok?(r.hardened?T("已撤回 ✅（按快照补全了整条）"):T("已撤回 ✅")):T("撤回失败：")+r.error);
      if(r.ok)refresh();
    };
  }
}
async function selfcheck(){
  toast(T("自检中…"));
  const r=await api("/api/selfcheck",{});
  alert((r.verdict||"")+"\n\n"+(r.checks||[]).map(c=>`${c.ok?"✓":"✗"} ${c.name}：${c.detail}`).join("\n"));
}
applyLang();
refresh();
</script></body></html>
"""

if __name__ == "__main__":
    main()
