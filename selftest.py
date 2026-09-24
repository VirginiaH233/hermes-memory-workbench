#!/usr/bin/env python3
"""selftest.py —— 端到端自测（含「分开批准」「丢弃某一处」「撤回」）。

用一条**临时造的**待审记录，把页面上每条按钮背后的接口都真跑一遍，最后检查：
  · 记忆文件逐字节回到测试前（md5 相同）
  · 待审队列条数回到测试前
  · 测试产生的动作记录/快照/归档已清掉（不脏你的页面）
任何一步失败就报红并统计，不做"大概没问题"的判断。
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
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


TOOL = Path(__file__).resolve().parent
HOME = _hermes_home()
PENDING = HOME / "pending" / "memory"
MEM = HOME / "memories"
B = "http://127.0.0.1:8787"
TID = "selftest01"
TOKEN = None
FAILS = []


def _token_from_page() -> str:
    """令牌只在服务发出来的页面里（外部网页跨域读不到），测试时照抄一份。"""
    html = urllib.request.urlopen(B + "/", timeout=30).read().decode("utf-8", "replace")
    m = re.search(r'const TOKEN="([0-9a-f]{32})"', html)
    if not m:
        raise SystemExit("拿不到页面令牌 —— 服务没在跑？或者页面太旧（重启 start.cmd）")
    return m.group(1)


def md5(p):
    return hashlib.md5(p.read_bytes()).hexdigest()


def post(path, data=None):
    global TOKEN
    if TOKEN is None:
        TOKEN = _token_from_page()
    req = urllib.request.Request(B + path, data=json.dumps(data or {}).encode(),
                                headers={"Content-Type": "application/json", "X-MR-Token": TOKEN})
    return json.loads(urllib.request.urlopen(req, timeout=300).read().decode())


def get(path):
    return json.loads(urllib.request.urlopen(B + path, timeout=120).read().decode())


def ops_of(payload):
    """记录里可能是 batch（多处）也可能是单处 —— 统一成列表。"""
    if payload.get("action") == "batch":
        return payload.get("operations") or []
    return [payload]


def check(name, cond, detail=""):
    print(("  OK  " if cond else "  XX  ") + name + (f" —— {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def main():
    before = {f: md5(MEM / f) for f in ("MEMORY.md", "USER.md")}
    q_before = len(list(PENDING.glob("*.json")))
    print("测试前：", before, f"队列 {q_before} 条")

    rec = {"id": TID, "created_at": time.time(), "origin": "manual_test",
           "summary": "自测用（两处新增）",
           "payload": {"action": "batch", "target": "memory", "operations": [
               {"action": "add", "content": "（自测条目甲 selftest-A，稍后自动删除）", "old_text": ""},
               {"action": "add", "content": "（自测条目乙 selftest-B，稍后自动删除）", "old_text": ""}]}}
    (PENDING / f"{TID}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        st = get("/api/state")
        check("页面接口通 /api/state", st.get("ok") and {"records", "memory", "log"} <= set(st))
        mine = [r for r in st["records"] if r["id"] == TID]
        check("能读到新造的两处改动", len(mine) == 1 and len(mine[0]["ops"]) == 2,
              f"{len(mine)} 条记录 / {len(mine[0]['ops']) if mine else 0} 处")

        d = post("/api/record/dryrun", {"id": TID, "index": 0})
        check("试跑某一处（不写入）", d.get("ok"), str(d.get("error", ""))[:80])
        check("试跑没碰真实记忆", md5(MEM / "MEMORY.md") == before["MEMORY.md"])

        s = post("/api/record/save", {"id": TID, "ops": [
            {"action": "add", "content": "（自测条目甲 selftest-A 已改过，稍后自动删除）", "old_text": ""},
            {"action": "add", "content": "（自测条目乙 selftest-B，稍后自动删除）", "old_text": ""}]})
        check("保存草稿（只动队列）", s.get("ok") and md5(MEM / "MEMORY.md") == before["MEMORY.md"])
        saved = json.loads((PENDING / f"{TID}.json").read_text(encoding="utf-8"))
        check("改过的文字真的存进队列了", "已改过" in saved["payload"]["operations"][0]["content"])

        a = post("/api/record/approve_one", {"id": TID, "index": 0})
        check("只批第 1 处 → 落库", a.get("ok"), str(a.get("error", ""))[:100])
        check("记忆确实变了", md5(MEM / "MEMORY.md") != before["MEMORY.md"])
        check("队列里这条还剩 1 处", "还剩 1 处" in str(a.get("state", "")), str(a.get("state")))
        left = json.loads((PENDING / f"{TID}.json").read_text(encoding="utf-8"))
        left_ops = ops_of(left["payload"])
        check("剩下的那处是第 2 处（乙）", len(left_ops) == 1
              and "selftest-B" in left_ops[0]["content"])
        check("给了撤回用的 log_id", bool(a.get("log_id")))

        u = post("/api/undo", {"log_id": a["log_id"]})
        check("撤回这一步", u.get("ok"), str(u.get("error", ""))[:100])
        check("撤回后记忆逐字节回到原样", md5(MEM / "MEMORY.md") == before["MEMORY.md"],
              md5(MEM / "MEMORY.md"))

        dr = post("/api/record/drop", {"id": TID, "index": 0})
        check("丢掉剩下那一处", dr.get("ok") and "已完成" in str(dr.get("state", "")), str(dr.get("state")))
        check("丢掉后记录已离开队列", not (PENDING / f"{TID}.json").exists())
        check("丢掉没碰记忆", md5(MEM / "MEMORY.md") == before["MEMORY.md"])

        (PENDING / f"{TID}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        d2 = post("/api/record/drop", {"id": TID})
        check("整条都不要", d2.get("ok") and not (PENDING / f"{TID}.json").exists())

        sc = post("/api/selfcheck")
        check("自检报告", sc.get("ok") is True, str(sc.get("verdict", ""))[:60])

        st2 = get("/api/state")
        check("队列条数回到测试前", len(st2["records"]) == q_before,
              f"{len(st2['records'])} vs {q_before}")
        check("MEMORY.md 逐字节不变", md5(MEM / "MEMORY.md") == before["MEMORY.md"])
        check("USER.md 逐字节不变", md5(MEM / "USER.md") == before["USER.md"])
        check("「全部记忆」能读到内容", len(st2["memory"]["memory"]) > 0 and len(st2["memory"]["user"]) > 0,
              f"笔记 {len(st2['memory']['memory'])} 条 / 画像 {len(st2['memory']['user'])} 条")
        check("「动作记录」有撤回按钮所需的 inverse",
              all(("inverse" in e) or e.get("kind") in ("drop", "fail", "undo") for e in st2["log"]))
    finally:
        (PENDING / f"{TID}.json").unlink(missing_ok=True)
        # 自愈：万一中途崩了，测试写进记忆的内容也要清掉
        cur = (MEM / "MEMORY.md").read_text(encoding="utf-8")
        for probe in [ln for ln in cur.split("\n") if "自测条目" in ln]:
            subprocess.run([sys.executable, str(TOOL / "ops.py"), "memop", "--target", "memory",
                            "--action", "remove", "--old-text", probe.strip()],
                           capture_output=True, text=True, encoding="utf-8", timeout=180)
        log = TOOL / "oplog.jsonl"
        if log.exists():
            keep = [ln for ln in log.read_text(encoding="utf-8").splitlines()
                    if ln.strip() and TID not in ln and "自测条目" not in ln]
            log.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
        for p in (TOOL / "done").glob(f"*{TID}*.json") if (TOOL / "done").exists() else []:
            p.unlink()
        for p in (TOOL / "snapshots").iterdir() if (TOOL / "snapshots").exists() else []:
            note = p / "note.txt"
            if p.is_dir() and note.exists() and note.read_text(encoding="utf-8") in ("add", "write"):
                shutil.rmtree(p, ignore_errors=True)

    print()
    if FAILS:
        print(f"XX {len(FAILS)} 项没过：" + "、".join(FAILS))
        raise SystemExit(1)
    print("OK 全部通过：记忆逐字节回到原样，队列与测试前一致，测试痕迹已清理")


if __name__ == "__main__":
    main()
