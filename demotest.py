#!/usr/bin/env python3
"""demotest.py —— 演示模式验收：假数据能用，真实记忆一个字节都不变。

这是 P1 最重要的一条：演示模式是给陌生人第一次打开用的，
它必须做到「随便点都碰不到真实记忆」，而且这一点要能被自动证明。

做法：
  ① 先记下真实记忆文件 + 真实动作记录/快照的指纹
  ② 另起一个进程跑 `server.py --demo --port 8899`（假档案在 demo-home/）
  ③ 在这个演示进程上：读状态 → 批准一条 → 改写一条 → 撤回一步
  ④ 再核对真实指纹：必须逐字节不变
  ⑤ 关掉演示进程，清掉痕迹
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOOL = Path(__file__).resolve().parent
PORT = 8899
BASE = f"http://127.0.0.1:{PORT}"
PY = sys.executable
FAILS: list = []


def ok(name: str, cond: bool, detail: str = ""):
    print(("  OK  " if cond else "  XX  ") + name + (f" —— {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def hermes_real_home() -> Path:
    for k in ("HERMES_HOME", "MR_HOME"):
        v = os.environ.get(k)
        if v:
            return Path(v)
    if os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes"
    return Path.home() / ".hermes"


REAL = hermes_real_home()
REAL_FILES = [REAL / "memories" / "MEMORY.md", REAL / "memories" / "USER.md",
              TOOL / "oplog.jsonl"]
REAL_SNAP = sorted((TOOL / "snapshots").glob("*")) if (TOOL / "snapshots").exists() else []
REAL_DONE = sorted((TOOL / "done").glob("*")) if (TOOL / "done").exists() else []


def fingerprint() -> dict:
    out = {}
    for p in REAL_FILES:
        out[str(p)] = hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else "missing"
    out["snapshots"] = len(REAL_SNAP)
    out["done"] = len(REAL_DONE)
    out["snap_names"] = ",".join(p.name for p in REAL_SNAP)
    return out


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8")), r.read() if False else None


def token() -> str:
    with urllib.request.urlopen(BASE + "/", timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
    import re
    m = re.search(r'const TOKEN="([0-9a-f]{32})"', body)
    if not m:
        raise SystemExit("拿不到页面令牌 —— 页面没起来？")
    return m.group(1)


def post(path: str, payload: dict, lang: str = ""):
    body = dict(payload)
    if lang:
        body["lang"] = lang
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "X-MR-Token": token(),
                 "Origin": BASE})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace"))


def get_html(path: str = "/", accept: str = "") -> str:
    req = urllib.request.Request(BASE + path, headers={"Accept-Language": accept} if accept else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def wait_up(timeout: float = 40.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            get("/api/state")
            return True
        except Exception:
            time.sleep(0.7)
    return False


def main() -> int:
    before = fingerprint()
    print(f"真实档案：{REAL}")
    print(f"真实记忆指纹：MEMORY.md={before[str(REAL_FILES[0])][:8]}… "
          f"USER.md={before[str(REAL_FILES[1])][:8]}…")

    # 端口要是被别人占着，测试就会去测「别人的服务」而自己毫无察觉（曾因此 13 项假失败）→ 先拦
    import socket as _sock
    _probe = _sock.socket()
    try:
        _probe.bind(("127.0.0.1", PORT))
    except OSError:
        print()
        print(f"端口 {PORT} 已被占用（多半是另开着的演示服务）—— 先关掉它再跑本测试。")
        print(f"  Windows: netstat -ano | findstr :{PORT}   然后 taskkill /F /PID <PID>")
        return 2
    finally:
        _probe.close()

    env = {**os.environ, "MR_NO_BROWSER": "1", "MR_PORT": str(PORT), "MR_LANG": "zh"}
    env.pop("HERMES_HOME", None)
    env.pop("MR_HOME", None)
    env.pop("MR_DATA_DIR", None)     # 演示进程自己会把它指到 demo-home
    log = open(TOOL / "demotest.log", "w", encoding="utf-8")
    proc = subprocess.Popen([PY, str(TOOL / "server.py"), "--demo", "--demo-reset",
                             "--port", str(PORT)], env=env, stdout=log, stderr=subprocess.STDOUT,
                            cwd=str(TOOL))
    try:
        print("\n1) 演示进程能起来")
        ok("演示服务在 40 秒内就绪", wait_up(), BASE)
        st, _ = get("/api/state")
        print("\n2) 演示档案的内容")
        ok("档案被认成演示模式", st.get("demo") is True, f"demo={st.get('demo')}")
        ok("门禁状态读到了", st.get("gate") is True, f"gate={st.get('gate')}")
        ok("队列里有 4 条演示提议", len(st.get("records") or []) == 4,
           f"{len(st.get('records') or [])} 条")
        ok("读到假的记忆（我的笔记 6 条）", len((st.get("memory") or {}).get("memory") or []) == 6,
           f"{len((st.get('memory') or {}).get('memory') or [])} 条")
        ok("读到假的画像（4 条）", len((st.get("memory") or {}).get("user") or []) == 4,
           f"{len((st.get('memory') or {}).get('user') or [])} 条")
        ok("演示的记忆上限显示正常", (st.get("limits") or {}).get("limits", {}).get("memory") == 2500 and
           (st.get("limits") or {}).get("limits", {}).get("user") == 2000,
           json.dumps((st.get("limits") or {}).get("limits"), ensure_ascii=False))
        ok("演示档案里没有混进真实快照/归档",
           not (st.get("snapshots") or []) and not (st.get("done") or []),
           f"snapshots={len(st.get('snapshots') or [])} done={len(st.get('done') or [])}")

        print("\n3) 真批准一条（新增）")
        s, r = post("/api/record/approve", {"id": "demo0001"})
        ok("批准成功", r.get("ok") is True, str(r.get("error") or "")[:90])
        st2, _ = get("/api/state")
        txt = "\n".join((st2.get("memory") or {}).get("memory") or [])
        ok("假记忆里出现了这条新内容", "杭州出差三天" in txt)
        ok("那条提议已从队列消失", all(x.get("id") != "demo0001" for x in (st2.get("records") or [])))

        print("\n4) 真改写一条并撤回（验证「撤得回去」—— 整条替换的撤回）")
        md5_before = hashlib.md5("\n".join((st2.get("memory") or {}).get("memory") or [])
                                 .encode("utf-8")).hexdigest()
        s, r = post("/api/record/approve_one", {"id": "demo0002", "index": 0})
        ok("第 1 处改动批准成功", r.get("ok") is True, str(r.get("error") or "")[:90])
        log_id = r.get("log_id", "")
        st3, _ = get("/api/state")
        mem3 = (st3.get("memory") or {}).get("memory") or []
        md5_after = hashlib.md5("\n".join(mem3).encode("utf-8")).hexdigest()
        ok("假记忆确实变了", md5_after != md5_before)
        ok("动作记录里有这一步（撤回按钮要用）", bool(log_id), log_id)
        # Hermes 的 replace 是「整条替换」：旧文只定位，命中的整条被覆盖。
        # 所以撤回必须把那一整条原文还原 —— 只塞回旧文片段会吃掉其余文字（这里就是回归点）。
        ok("覆盖是整条的（其余文字确实一起被换掉）",
           not any("项目代号「贝壳」" in x for x in mem3) and any("只保留单账户记账" in x for x in mem3),
           "；".join(x[:34] for x in mem3 if "记账" in x))
        if log_id:
            s, r = post("/api/undo", {"log_id": log_id})
            ok("撤回成功", r.get("ok") is True, str(r.get("error") or "")[:90])
            st4, _ = get("/api/state")
            mem4 = (st4.get("memory") or {}).get("memory") or []
            md5_back = hashlib.md5("\n".join(mem4).encode("utf-8")).hexdigest()
            ok("撤回后假记忆逐字节回到原样", md5_back == md5_before,
               "；".join(x[:30] for x in mem4 if "记账" in x))

        print("\n4.5) 整条替换的撤回必须还原「一整条」，不能只剩旧文片段（回归）")
        s, r = post("/api/record/approve_one", {"id": "demo0003", "index": 0})
        ok("批量里的第 1 处批准成功", r.get("ok") is True, str(r.get("error") or "")[:90])
        if r.get("ok") and r.get("log_id"):
            s, u = post("/api/undo", {"log_id": r["log_id"]})
            st5, _ = get("/api/state")
            mem5 = (st5.get("memory") or {}).get("memory") or []
            ok("撤回后那一整条完整回来（含没被改动的部分）",
               any("常用快捷键 Ctrl+Shift+P" in x for x in mem5) and any("主力编辑器是 VS Code" in x for x in mem5),
               "；".join(x[:40] for x in mem5 if "编辑器" in x))

        print("\n4.6) 老式记录（只有旧文片段）的撤回：必须按当时快照补全整条")
        demo_home = TOOL / "demo-home"
        data = demo_home / "data"
        mem_file = demo_home / "memories" / "MEMORY.md"
        user_file = demo_home / "memories" / "USER.md"
        FULL = "阿岸喜欢手冲咖啡，最近在研究浅烘焙的耶加雪菲，周末常在家自己冲。"
        FRAG = "浅烘焙的耶加雪菲"
        NEW = "最近只喝美式，咖啡器具都收起来了。"
        cur_entries = [e for e in mem_file.read_text(encoding="utf-8").split("\n§\n") if e.strip()]
        # ① 造一份「当时」的快照（里面的那一条是完整的）
        snap_name = "20990101-000000-replace-old1"
        sd = data / "snapshots" / snap_name
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "MEMORY.md").write_text("\n§\n".join([FULL.strip()] + [x.strip() for x in cur_entries]) + "\n",
                                      encoding="utf-8")
        (sd / "USER.md").write_text(user_file.read_text(encoding="utf-8"), encoding="utf-8")
        (sd / "profile.txt").write_text("default", encoding="utf-8")
        (sd / "note.txt").write_text("replace", encoding="utf-8")
        # ② 模拟「旧版本写入过的那一步」：那一条现在只剩新内容
        mem_file.write_text("\n§\n".join([NEW] + [x.strip() for x in cur_entries]) + "\n", encoding="utf-8")
        # ③ 手工补一条「老式」日志：反向操作里只有片段，没有整条原文
        old_line = {"log_id": "old001", "kind": "memop", "target": "memory",
                    "desc": f"整条替换「{FRAG}」→「{NEW}」",
                    "inverse": {"action": "replace", "target": "memory", "content": FRAG, "old_text": NEW},
                    "snapshot": snap_name, "before": "0/2,500", "after": "0/2,500",
                    "profile": "default", "at": time.time()}
        with open(data / "oplog.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(old_line, ensure_ascii=False) + "\n")
        s, r = post("/api/undo", {"log_id": "old001"})
        ok("老式撤回成功", r.get("ok") is True, str(r.get("error") or "")[:90])
        ok("撤回时报告了「已按快照补全」", bool(r.get("hardened")), f"hardened={r.get('hardened')}")
        st6, _ = get("/api/state")
        mem6 = (st6.get("memory") or {}).get("memory") or []
        ok("那一整条原文回来了（不是只剩片段）", FULL in mem6,
           "；".join(x[:36] for x in mem6 if "咖啡" in x or "美式" in x))

        print("\n5) 自检（演示档案也要能自检通过）")
        h = json.loads(subprocess.run(
            [PY, str(TOOL / "ops.py"), "selfcheck"],
            env={**env, "MR_HOME": str(TOOL / "demo-home"),
                 "MR_DATA_DIR": str(TOOL / "demo-home" / "data"),
                 "MR_PROFILE": "default"},
            capture_output=True, text=True, encoding="utf-8", cwd=str(TOOL)).stdout.strip().splitlines()[-1])
        bad = [c for c in (h.get("checks") or []) if not c.get("ok")]
        ok("演示档案的自检全通过", bool(h.get("checks")) and not bad,
           "; ".join(f"{c['name']}:{c['detail']}" for c in bad)[:160] or f"{len(h.get('checks') or [])} 项")
        print("\n6) 多档案：中途新增 / 只有配置文件（还没写过记忆）/ 正在看的被删掉")
        newp = TOOL / "demo-home" / "profiles" / "新同事"
        (newp / "memories").mkdir(parents=True, exist_ok=True)
        (newp / "memories" / "MEMORY.md").write_text("新同事档案的第一条\n§\n第二条\n", encoding="utf-8")
        (newp / "memories" / "USER.md").write_text("新同事的画像一条\n", encoding="utf-8")
        (newp / "config.yaml").write_text(
            "memory:\n  memory_char_limit: 1200\n  user_char_limit: 900\n  write_approval: true\n",
            encoding="utf-8")
        st7, _ = get("/api/state")
        names = [x["name"] for x in st7["profiles"]]
        ok("中途新增的档案自动出现（没重启服务）", "新同事" in names, "、".join(names))
        st8, _ = get("/api/state?profile=" + urllib.parse.quote("新同事"))
        ok("能读新档案自己的记忆", len((st8.get("memory") or {}).get("memory") or []) == 2,
           f"{len((st8.get('memory') or {}).get('memory') or [])} 条")
        ok("用的是新档案自己的字数上限", (st8.get("limits") or {}).get("limits", {}).get("memory") == 1200,
           json.dumps((st8.get("limits") or {}).get("limits"), ensure_ascii=False))
        ok("读的是新档案自己的门禁", st8.get("gate") is True, f"gate={st8.get('gate')}")

        half = TOOL / "demo-home" / "profiles" / "刚建的档案"
        half.mkdir(parents=True, exist_ok=True)
        (half / "config.yaml").write_text("memory:\n  memory_char_limit: 2000\n", encoding="utf-8")
        st9, _ = get("/api/state")
        names9 = [x["name"] for x in st9["profiles"]]
        ok("刚建好、还没写过记忆的档案也列出来（否则用户以为工具坏了）",
           "刚建的档案" in names9, "、".join(names9))

        shutil.rmtree(newp, ignore_errors=True)
        st10, _ = get("/api/state?profile=" + urllib.parse.quote("新同事"))
        ok("正在看的档案被删掉 → 明确报「找不到」，不拿 default 的记忆冒充",
           st10.get("ok") is False and st10.get("stale_profile") is True and "records" not in st10,
           str(st10.get("error"))[:80])
        s, r = post("/api/record/save", {"profile": "新同事", "id": "demo0001", "ops": []})
        ok("对已不存在的档案发写操作 → 被拒、不落到别的档案",
           r.get("ok") is False and "找不到档案" in str(r.get("error")), str(r.get("error"))[:80])

        print("\n7) 英文模式（海外用户）：页面/提示/报错都出英文")
        import re
        zh = re.compile(r"[\u4e00-\u9fff]")

        def leftover_zh(text: str) -> list:
            """引号里的原文（用户自己的记忆）永远不翻，先挖掉；剩下的中文才算「漏翻」。"""
            return zh.findall(re.sub(r"'[^']*'|\"[^\"]*\"|“[^”]*”", "", text or ""))

        page_en = get_html("/", "en-US,en;q=0.9")
        ok("英文浏览器拿到英文模式（服务端按 Accept-Language 判）", '"lang": "en"' in page_en)
        ok("英文页面里带着英文词典（页面靠它出英文）",
           '"en": {' in page_en and '"Pending proposals"' in page_en and '"All memory"' in page_en)
        page_zh = get_html("/", "zh-CN,zh;q=0.9")
        ok("中文浏览器拿到中文模式（页面按浏览器语言一开始就是中文）",
           '"lang": "zh"' in page_zh and "待审提议" in page_zh)
        ok("中文页面也带着英文词典（右上角那个语言按钮要在页内切得动）",
           '"en": {' in page_zh and '"Pending proposals"' in page_zh)
        ok("同一台机器两种语言各拿各的", '"lang": "en"' not in page_zh)

        # 卡片上的红字提示（note）也必须是英文 —— 这是用户真正看到的「为什么批不了」
        st_en, _ = get("/api/state?lang=en")
        rec4_en = next((r for r in (st_en.get("records") or []) if r.get("id") == "demo0004"), {})
        note_en = " ".join((o.get("note") or "") for o in (rec4_en.get("ops") or []))
        ok("英文模式：卡片上的失效提示是英文",
           bool(note_en) and not zh.search(note_en), note_en[:90])
        st_zh, _ = get("/api/state?lang=zh")
        rec4_zh = next((r for r in (st_zh.get("records") or []) if r.get("id") == "demo0004"), {})
        note_zh = " ".join((o.get("note") or "") for o in (rec4_zh.get("ops") or []))
        ok("中文模式：同一条卡片提示是中文", bool(zh.search(note_zh)), note_zh[:60])

        # 英文的一条龙：批准 → 看提示 → 撤回（demo0003 是批量，批准 1 处后还剩 1 处）
        s, r = post("/api/record/approve_one", {"id": "demo0003", "index": 0}, lang="en")
        ok("英文模式下批准成功", r.get("ok") is True, str(r.get("error") or "")[:80])
        ok("批准后的提示是英文",
           bool(r.get("message")) and not zh.search(str(r.get("message"))), str(r.get("message"))[:80])
        ok("字数变化那行也是英文", not zh.search(str(r.get("state") or "")), str(r.get("state"))[:80])
        if r.get("log_id"):
            st_l, _ = get("/api/state?lang=en")
            row = next((x for x in (st_l.get("log") or []) if x.get("log_id") == r["log_id"]), {})
            ok("动作记录里这一步的描述（desc）是英文",
               bool(row) and not leftover_zh(str(row.get("desc"))), str(row.get("desc"))[:80])
            ok("动作记录里的其它字段没被误翻（时间是数字、字数是原样）",
               isinstance(row.get("ts"), (int, float)) and bool(row.get("after")),
               json.dumps(row, ensure_ascii=False)[:90])
            s, u = post("/api/undo", {"log_id": r["log_id"]}, lang="en")
            ok("英文模式下撤回成功", u.get("ok") is True, str(u.get("error") or "")[:80])
            ok("撤回后的提示也是英文",
               not zh.search(str(u.get("message") or "")), str(u.get("message"))[:80])

        # 用户自己的记忆与档案内容永远不翻
        st13, _ = get("/api/state?lang=en")
        ok("英文模式下用户自己的记忆保持原样（永不翻译）",
           "阿岸" in json.dumps(st13.get("memory") or {}, ensure_ascii=False))
        ok("英文模式下档案名保持原样", any("demo" in str(p.get("name", "")) or zh.search(str(p.get("name", "")))
                                        for p in (st13.get("profiles") or [])))
        # 我们自己的报错不许露中文（Hermes 原生报错本就是英文，不去动它）
        s, r = post("/api/record/approve", {"id": "demo0004"}, lang="en")
        ok("英文模式下批准失效提议 → 报错里没有我们的中文模板",
           r.get("ok") is False and not leftover_zh(str(r.get("error") or "")),
           "".join(leftover_zh(str(r.get("error") or "")))[:40] or str(r.get("error"))[:70])
        s, r = post("/api/record/save", {"id": "不存在-的提议", "ops": []}, lang="en")
        ok("英文模式下「编号不合法」是英文（这条是我们自己写的）",
           r.get("ok") is False and "Invalid record id" in str(r.get("error")),
           str(r.get("error"))[:90])
        s, r = post("/api/record/save", {"id": "no_such_rec", "ops": []}, lang="en")
        ok("英文模式下「队列里找不到这条记录」是英文",
           r.get("ok") is False and "is gone" in str(r.get("error"))
           and not leftover_zh(str(r.get("error"))), str(r.get("error"))[:90])
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()

    print("\n8) 回到真实档案：逐字节核对（这是本测试的重点）")
    after = fingerprint()
    for p in REAL_FILES:
        ok(f"{Path(p).name} 没变", before[str(p)] == after[str(p)],
           f"{before[str(p)][:8]}… → {after[str(p)][:8]}…")
    ok("真实快照数量没变", before["snapshots"] == after["snapshots"],
       f"{before['snapshots']} → {after['snapshots']}")
    ok("真实归档数量没变", before["done"] == after["done"], f"{before['done']} → {after['done']}")
    ok("真实快照目录没多出新东西", before["snap_names"] == after["snap_names"])

    print()
    if FAILS:
        print(f"XX {len(FAILS)} 项没过：{'、'.join(FAILS)}")
        return 1
    print("OK 演示模式验收全部通过：假数据能用（批准/改写/撤回/自检都通），真实记忆逐字节没变")
    return 0


if __name__ == "__main__":
    sys.exit(main())
