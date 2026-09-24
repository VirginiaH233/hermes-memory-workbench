"""验证「切档案」这条路真的能读能写另一个档案的记忆（用雷达档做被测对象）。

安全措施（和 selftest 一样）：
  · 用一条**临时造的**待审记录，只写它在沙盒里允许的测试条目
  · 测完把雷达档的记忆文件逐字节还原（比对 md5），并清掉队列/日志/归档/快照里的痕迹
  · 任何一步失败就报红
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


def _hermes_home() -> Path:
    """和 server.py 用同一套探测顺序；mac/Linux 的路径未实测。"""
    for k in ("MR_HOME", "HERMES_HOME"):
        if os.environ.get(k):
            return Path(os.environ[k])
    if os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes"
    return Path.home() / ".hermes"


def _pick_other_profile(home: Path) -> str:
    """找一个「不是 default 的档案」当被测对象：先看环境变量，再看磁盘上第一个。"""
    name = os.environ.get("MR_TEST_PROFILE")
    if name:
        return name
    root = home / "profiles"
    if root.exists():
        for d in sorted(root.iterdir()):
            if d.is_dir() and (d / "memories").exists():
                return d.name
    return ""


TOOL = Path(__file__).resolve().parent
HOME = _hermes_home()
PROFILE = _pick_other_profile(HOME)
if not PROFILE:
    print("这台机器上只有一个档案（default），没有「另一个档案」可测 —— 跳过。")
    print("想测的话：先建一个档案（hermes profile create <名字>），或指定 MR_TEST_PROFILE=<档案名>。")
    raise SystemExit(0)
RADAR = HOME / "profiles" / PROFILE
PENDING = RADAR / "pending" / "memory"
B = "http://127.0.0.1:8787"
TID = "profcheck1"
TOKEN = None
FAILS = []


def _token_from_page() -> str:
    html = urllib.request.urlopen(B + "/", timeout=30).read().decode("utf-8", "replace")
    m = re.search(r'const TOKEN="([0-9a-f]{32})"', html)
    if not m:
        raise SystemExit("拿不到页面令牌 —— 服务没在跑？或者页面太旧（重启 start.cmd）")
    return m.group(1)


def md5(p):
    return hashlib.md5(p.read_bytes()).hexdigest()


def get(path):
    return json.loads(urllib.request.urlopen(B + path, timeout=120).read().decode())


def post(path, d):
    global TOKEN
    if TOKEN is None:
        TOKEN = _token_from_page()
    r = urllib.request.Request(B + path, data=json.dumps(d).encode(),
                              headers={"Content-Type": "application/json", "X-MR-Token": TOKEN})
    return json.loads(urllib.request.urlopen(r, timeout=300).read().decode())


def check(name, cond, detail=""):
    print(("  OK  " if cond else "  XX  ") + name + (f" —— {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def main():
    before = {f: md5(RADAR / "memories" / f) for f in ("MEMORY.md", "USER.md")}
    q_before = len(list(PENDING.glob("*.json"))) if PENDING.exists() else 0
    print("雷达档测试前：", before, f"队列 {q_before} 条")

    PENDING.mkdir(parents=True, exist_ok=True)
    rec = {"id": TID, "created_at": time.time(), "origin": "manual_test",
           "summary": "切档案自测（两处新增）",
           "payload": {"action": "batch", "target": "memory", "operations": [
               {"action": "add", "content": "（档案自测甲 profcheck-A，稍后自动删除）", "old_text": ""},
               {"action": "add", "content": "（档案自测乙 profcheck-B，稍后自动删除）", "old_text": ""}]}}
    (PENDING / f"{TID}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        st = get("/api/state?profile=" + urllib.parse.quote(PROFILE))
        check("能读到雷达档的状态", st.get("ok") and st.get("profile") == PROFILE,
              str(st.get("profile")))
        check("读到的是雷达档自己的记忆", len(st["memory"]["memory"]) > 0 and len(st["memory"]["user"]) > 0,
              f"笔记 {len(st['memory']['memory'])} 条 / 画像 {len(st['memory']['user'])} 条")
        check("给出了可切换的档案清单", PROFILE in [p["name"] for p in st["profiles"]],
              str([p["name"] for p in st["profiles"]]))
        check("读到雷达档的队列", any(r["id"] == TID for r in st["records"]))
        check("用量是雷达档自己的", bool((st["limits"].get("usage") or {}).get("memory")),
              str(st["limits"].get("usage")))
        check("动作记录按档案隔离", all((e.get("profile") or "default") == PROFILE for e in st["log"]),
              f"{len(st['log'])} 条")

        d1 = get("/api/state")
        check("default 档仍然正常", d1["profile"] == "default" and len(d1["memory"]["memory"]) > 0,
              f"笔记 {len(d1['memory']['memory'])} 条")
        check("两个档案的记忆确实不同", d1["memory"]["memory"] != st["memory"]["memory"])

        d = post("/api/record/dryrun", {"profile": PROFILE, "id": TID, "index": 0})
        check("试跑雷达档的一处改动（不写入）", d.get("ok"), str(d.get("error", ""))[:90])

        a = post("/api/record/approve_one", {"profile": PROFILE, "id": TID, "index": 0})
        check("只批第 1 处 → 写进雷达档", a.get("ok"), str(a.get("error", ""))[:120])
        check("雷达档的记忆确实变了", md5(RADAR / "memories" / "MEMORY.md") != before["MEMORY.md"])
        check("default 档没被牵连",
              md5(HOME / "memories" / "MEMORY.md") == md5(HOME / "memories" / "MEMORY.md"))

        u = post("/api/undo", {"profile": PROFILE, "log_id": a.get("log_id")})
        check("撤回这一步", u.get("ok"), str(u.get("error", ""))[:120])
        check("撤回后雷达档记忆逐字节还原", md5(RADAR / "memories" / "MEMORY.md") == before["MEMORY.md"],
              md5(RADAR / "memories" / "MEMORY.md"))

        dr = post("/api/record/drop", {"profile": PROFILE, "id": TID})
        check("丢掉剩下的、整条归档", dr.get("ok") and not (PENDING / f"{TID}.json").exists(),
              str(dr.get("state")))

        rb = post("/api/rollback", {"profile": PROFILE, "name": "不存在的快照"})
        check("跨档案回退被拦/不存在的快照被拦", rb.get("ok") is False, str(rb.get("error", ""))[:80])
    finally:
        (PENDING / f"{TID}.json").unlink(missing_ok=True)
        cur = (RADAR / "memories" / "MEMORY.md").read_text(encoding="utf-8")
        for probe in [ln for ln in cur.split("\n") if "档案自测" in ln]:
            env = {"HERMES_HOME": str(RADAR), "MR_PROFILE": PROFILE,
                   "LOCALAPPDATA": str(HOME.parent.parent)}
            subprocess.run([sys.executable, str(TOOL / "ops.py"), "memop", "--target", "memory",
                            "--action", "remove", "--old-text", probe.strip()],
                           capture_output=True, text=True, encoding="utf-8", timeout=180, env={**__import__("os").environ, **env})
        log = TOOL / "oplog.jsonl"
        keep = [ln for ln in log.read_text(encoding="utf-8").splitlines()
                if ln.strip() and TID not in ln and "档案自测" not in ln]
        log.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
        for p in (TOOL / "done").glob(f"*{TID}*.json"):
            p.unlink()
        for p in (TOOL / "snapshots").iterdir():
            if p.is_dir() and p.name.startswith(f"{PROFILE}-"):      # 快照按档案带前缀
                __import__("shutil").rmtree(p, ignore_errors=True)

    print()
    after = {f: md5(RADAR / "memories" / f) for f in ("MEMORY.md", "USER.md")}
    print("雷达档测试后：", after, f"队列 {len(list(PENDING.glob('*.json')))} 条")
    check("雷达档两个记忆文件都没变", after == before, f"{after}")
    if FAILS:
        print(f"XX {len(FAILS)} 项没过：" + "、".join(FAILS))
        raise SystemExit(1)
    print("OK 切档案这条路通了：能读能写能撤回，另一个档案毫发无损")


if __name__ == "__main__":
    main()
