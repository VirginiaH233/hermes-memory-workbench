#!/usr/bin/env python3
"""ops.py —— 所有会碰到 Hermes 记忆的动作，都在这里，且每次都是独立进程。

为什么单独一层：页面服务本身不 import Hermes 任何代码，只做文件读写和排版；
真正"落库"这一步委托给这个脚本。这样即使 Hermes 更新导致某个内部名字变了，
坏掉的也只是这一步（会明确报错），不会连带页面或记忆出问题。

子命令（都往 stdout 打 JSON）：
  limits                         当前生效的字数上限
  apply <id> [--index N]         落库：省略 N = 整条；给了 N = 只落第 N 处，其余留在队列
  dryrun <id> [--index N]        沙盒试跑，不碰真实记忆
  drop <id> [--index N]          把某处（或整条）移进「已完成」，不写记忆
  memop --target --action --content [--old-text]   改「当前记忆」的某一条
  undo <log_id>                  撤回动作记录里的某一步（精确反向操作，不动别的条目）
  log [--limit N]                动作记录
  rollback <快照目录名>          把记忆文件整档退回某个快照
  selfcheck                      自检：还能不能读写、能不能试跑
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

def _hermes_home() -> Path:
    """Hermes 的家目录：Hermes 自己也是靠这些环境变量定位的。mac/Linux 未实测。"""
    for k in ("HERMES_HOME", "MR_HOME"):
        if os.environ.get(k):
            return Path(os.environ[k])
    if os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes"
    return Path.home() / ".hermes"


def _agent_dir(home: Path) -> str:
    """Hermes 源码目录：先看环境变量，再从家目录往上几层找 hermes-agent。

    注意非 default 档案的家目录是 <hermes>/profiles/<名>，源码在 <hermes>/hermes-agent ——
    所以要往上找两层（这层曾经漏掉，切档案的测试直接报红）。
    """
    env = os.environ.get("MR_AGENT_DIR")
    if env:
        return env
    cands = [home / "hermes-agent", home.parent / "hermes-agent", home.parent.parent / "hermes-agent",
             Path.home() / "hermes-agent", Path.home() / ".hermes" / "hermes-agent"]
    # 演示档案不在 Hermes 家目录下面（它是工具自己的子目录），所以还要认「这台机器上 Hermes 装在哪」
    for base in (os.environ.get("LOCALAPPDATA"),):
        if base:
            cands.append(Path(base) / "hermes" / "hermes-agent")
    for cand in cands:
        if (cand / "tools" / "memory_tool.py").exists():
            return str(cand)
    return ""   # 找不到也要能跑：真要写入时会给出人话错误，不会写坏记忆


HOME = _hermes_home()
AGENT_DIR = _agent_dir(HOME)
PROFILE = os.environ.get("MR_PROFILE") or ("default" if HOME.name == "hermes" else HOME.name)
os.environ["HERMES_HOME"] = str(HOME)  # 让 Hermes 自己的记忆模块也认这个档案
TAG = "" if PROFILE == "default" else f"{PROFILE}-"
TOOL_DIR = Path(__file__).resolve().parent
if AGENT_DIR:
    sys.path.insert(0, AGENT_DIR)

FILES = ("MEMORY.md", "USER.md")
FILES_BY_TARGET = {"memory": "MEMORY.md", "user": "USER.md"}
ENTRY_SEP = "\n§\n"          # 记忆文件里条目之间的分隔（读快照时要用）
# 动作记录 / 快照 / 归档放哪。演示模式把 MR_DATA_DIR 指到隔离目录，
# 免得演示数据混进真实的操作记录里。
DATA_DIR = Path(os.environ.get("MR_DATA_DIR") or TOOL_DIR)
LOG = DATA_DIR / "oplog.jsonl"


# ---------- 基础 ----------
import i18n as _i18n          # 提示文案的中英词典（与页面共用一份）

MR_LANG = os.environ.get("MR_LANG", "zh")     # 由 server.py 按请求的语言注入


def out(obj, code=0):
    print(json.dumps(_i18n.tr_obj(obj, MR_LANG), ensure_ascii=False))
    sys.exit(code)


def memories_dir() -> Path:
    return HOME / "memories"


def pending_dir() -> Path:
    return HOME / "pending" / "memory"


# ---------- 外部输入当路径：一律先校验 ----------
# 队列编号、快照目录名都会从网页请求里来，不校验的话 `../../x` 就能读写到
# 队列/快照目录以外的文件（同类项目踩过这个洞）。所以只放行「我们自己生成的名字」，
# 再解析一遍确认没越出目录。
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}(\.json)?$")


def _die(obj):
    """直接退出时的统一出口：也要过一遍词典（否则英文模式下这几条会是中文）。"""
    raise SystemExit(json.dumps(_i18n.tr_obj(obj, MR_LANG), ensure_ascii=False))


def _safe_child(base: Path, name: str, what: str) -> Path:
    raw = str(name or "")
    if not _SAFE_NAME.match(raw):
        shown = raw[:-5] if raw.endswith(".json") else raw      # 报错时展示原始编号，别带后缀
        what_l = _i18n.t(what, MR_LANG)                          # 标签先翻，整句才好翻
        _die({"ok": False, "error": f"{what_l}不合法：{shown[:40]!r}（只允许字母、数字、- 和 _，64 字以内）"})
    root = base.resolve()
    p = root / raw
    try:
        p.resolve().relative_to(root)
    except ValueError:
        _die({"ok": False, "error": f"{what}不合法（越出目录）"})
    return p


def rec_path(rec_id: str) -> Path:
    return _safe_child(pending_dir(), f"{rec_id}.json", "记录编号")


def snap_path(name: str) -> Path:
    return _safe_child(snapshots_dir(), str(name), "快照名")


def snapshots_dir() -> Path:
    return DATA_DIR / "snapshots"


def done_dir() -> Path:
    return DATA_DIR / "done"


def snapshot(reason: str = "") -> str:
    """给记忆文件拍一张照片，返回目录名（非 default 档案带档案名前缀，便于区分）。"""
    name = TAG + time.strftime("%Y%m%d-%H%M%S") + (f"-{reason}" if reason else "") + "-" + uuid.uuid4().hex[:4]
    dst = snapshots_dir() / name
    dst.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        src = memories_dir() / f
        if src.exists():
            shutil.copy2(src, dst / f)
    (dst / "note.txt").write_text(reason, encoding="utf-8")
    (dst / "profile.txt").write_text(PROFILE, encoding="utf-8")
    return name


def load_record(rec_id: str) -> dict:
    p = rec_path(rec_id)
    if not p.exists():
        _die({"ok": False, "error": f"队列里找不到记录 {rec_id}（可能已在别处处理）"})
    return json.loads(p.read_text(encoding="utf-8"))


def rec_ops(payload: dict) -> list:
    if payload.get("action") == "batch":
        return list(payload.get("operations") or [])
    return [payload]


def write_ops(rec_id: str, target: str, ops: list) -> None:
    """把剩下（或改过）的几处写回队列记录；一处不剩就删掉记录文件。"""
    p = pending_dir() / f"{rec_id}.json"
    clean = [{"action": o.get("action"), "content": o.get("content", ""), "old_text": o.get("old_text", "")}
             for o in ops]
    if not clean:
        p.unlink(missing_ok=True)
        return
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["payload"] = ({"action": "batch", "target": target, "operations": clean} if len(clean) > 1
                      else {**clean[0], "target": target})
    rec["edited"] = True
    rec["edited_at"] = time.time()
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")


def archive(rec_id: str, kind: str, extra: dict) -> str:
    """把队列里的记录移入 done/（不删除，留档）。"""
    src = pending_dir() / f"{rec_id}.json"
    done_dir().mkdir(parents=True, exist_ok=True)
    name = TAG + f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}-{rec_id}-{uuid.uuid4().hex[:4]}.json"
    body = {"archived_at": time.time(), "kind": kind, "profile": PROFILE, **extra}
    if src.exists():
        try:
            body["record"] = json.loads(src.read_text(encoding="utf-8"))
        except Exception:
            pass
        src.unlink()
    (done_dir() / name).write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return name


# ---------- 动作记录（每一步都能撤回） ----------
def log_action(entry: dict) -> str:
    entry = {"log_id": uuid.uuid4().hex[:8], "ts": time.time(), "profile": PROFILE, **entry}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry["log_id"]


def read_log(limit: int = 40) -> list:
    if not LOG.exists():
        return []
    rows = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows[-limit:][::-1]


def inverse_of(action: str, target: str, content: str, old_text: str, lost: str = ""):
    """一步操作的反向操作 —— 撤回用它：精确，不牵连别的条目。

    关键：Hermes 的 replace/remove 都是**整条**动作（old_text 只负责定位，命中的
    整条被覆盖或删除）。所以反向操作必须用「原来那一整条」`lost`，只塞回旧文片段
    会把整条其余的文字弄丢 —— 这是实测抓到的真 bug。
    """
    if action == "add":
        return {"action": "remove", "target": target, "content": "", "old_text": content}
    if action == "remove":
        return {"action": "add", "target": target, "content": lost or old_text, "old_text": ""}
    if action == "replace":
        return {"action": "replace", "target": target, "content": lost or old_text, "old_text": content}
    return None


def describe(action: str, content: str, old_text: str) -> str:
    def cut(s, n=30):
        s = (s or "").replace("\n", " ")
        return s if len(s) <= n else s[:n] + "…"
    if action == "add":
        return f"新增「{cut(content, 40)}」"
    if action == "remove":
        return f"删除整条「{cut(old_text, 40)}」（旧文用来定位是哪一条）"
    return f"整条替换「{cut(old_text)}」→「{cut(content)}」"


# ---------- Hermes 那一侧 ----------
def hermes():
    """只碰 Hermes 的两个入口。这是全工具唯一「摸到系统内部」的地方 ——
    所以也是升级风险唯一集中的地方：名字一变，这里会明确报错，绝不会写坏记忆。"""
    if not AGENT_DIR:
        out({"ok": False, "error": "找不到 Hermes 源码目录 —— 设一下环境变量 MR_AGENT_DIR 指向 hermes-agent 目录"},
            1)
    try:
        from tools.memory_tool import load_on_disk_store, apply_memory_pending
    except ImportError as e:
        out({"ok": False, "error": f"装不上 Hermes 的记忆模块（{e}）—— "
                                  f"你的 Hermes 版本可能不兼容，或者 MR_AGENT_DIR 指错了：{AGENT_DIR}"}, 1)
    return load_on_disk_store, apply_memory_pending


def sandbox() -> str:
    """沙盒家目录：记忆文件 + 真实 config 都要带进去。

    只带记忆文件、不带 config 的话，字数上限会退化成出厂默认值，
    试跑结论会全错（这个坑踩过一次，别再踩）。
    """
    tmp = tempfile.mkdtemp(prefix="mr-dryrun-")
    (Path(tmp) / "memories").mkdir(parents=True, exist_ok=True)
    for f in FILES:
        src = memories_dir() / f
        if src.exists():
            shutil.copy2(src, Path(tmp) / "memories" / f)
    cfg = HOME / "config.yaml"
    if cfg.exists():
        shutil.copy2(cfg, Path(tmp) / "config.yaml")
    return tmp


def usage_of(store) -> dict:
    return {t: store._usage(t) for t in ("memory", "user")}


def matched_entry(store, payload: dict) -> str:
    """按 Hermes 的规则，找出「这条旧文指向的那一整条」原文。

    规则来自 Hermes 源码 `_find_unique_match`：整条**完全相等**优先，
    没有相等的才退而求其次用「包含」；命中多条不同的条目算歧义（返回空）。
    为什么需要它：replace/remove 都是**整条**动作，old_text 只负责定位 ——
    不知道原文那一整条，撤回时就会把整条其余的文字弄丢。
    """
    old = (payload.get("old_text") or "").strip()
    if not old:
        return ""
    try:
        entries = list(store._entries_for(payload.get("target", "memory")))
    except Exception:  # noqa: BLE001
        return ""
    exact = [e for e in entries if e == old]
    hits = exact if exact else [e for e in entries if old in e]
    if len(set(hits)) > 1:
        return ""
    return hits[0] if hits else ""


def run_payload(payload: dict, dry: bool = False):
    """执行一次写入 → (结果, 写前用量, 写后用量, 快照名)。

    结果里额外带上 `lost_entry`：这一步会**整条覆盖/删掉**的原文。
    Hermes 自己只在 replace 时返回 `replaced_entry`；remove 不给，
    所以这里两边都预先抓一份（抓法和 Hermes 的匹配规则一致）。
    """
    act = payload.get("action", "")
    watch = act in ("replace", "remove")

    def attach(res: dict, pre: str) -> dict:
        if isinstance(res, dict) and watch:
            lost = res.get("replaced_entry") or pre        # 原生给的为准，抓不到才用我们预抓的
            res["replaced_entry"] = lost
            res["lost_entry"] = lost
        return res

    if dry:
        tmp = sandbox()
        try:
            os.environ["HERMES_HOME"] = tmp
            load_store, apply_pending = hermes()
            s = load_store()
            pre = matched_entry(s, payload) if watch else ""
            before = usage_of(s)
            res = apply_pending(payload, s)
            return attach(res, pre), before, usage_of(load_store()), None
        finally:
            os.environ["HERMES_HOME"] = str(HOME)
            shutil.rmtree(tmp, ignore_errors=True)
    snap = snapshot(act or "write")
    load_store, apply_pending = hermes()
    s = load_store()
    pre = matched_entry(s, payload) if watch else ""
    before = usage_of(s)
    res = apply_pending(payload, s)
    return attach(res, pre), before, usage_of(load_store()), snap


def pick_op(payload: dict, index: int):
    ops = rec_ops(payload)
    if not (0 <= index < len(ops)):
        out({"ok": False, "error": f"这条记录里没有第 {index + 1} 处改动"}, 1)
    o = ops[index]
    return {"action": o.get("action"), "target": payload.get("target", "memory"),
            "content": o.get("content", ""), "old_text": o.get("old_text", "")}


# ---------- 子命令 ----------
def cmd_limits(_a):
    load_store, _ = hermes()
    s = load_store()
    out({"ok": True, "usage": usage_of(s),
         "limits": {"memory": s._char_limit("memory"), "user": s._char_limit("user")}})


def cmd_apply(args):
    rec = load_record(args.id)
    full = rec["payload"]
    target = full.get("target", "memory")
    ops = rec_ops(full)
    if args.index is None:
        one, label, rest = full, f"整条（{len(ops)} 处）", []
    else:
        one, label, rest = pick_op(full, args.index), f"第 {args.index + 1} 处", \
            ops[:args.index] + ops[args.index + 1:]
    res, before, after, snap = run_payload(one)
    desc = describe(one.get("action", ""), one.get("content", ""), one.get("old_text", ""))
    if not res.get("success"):
        log_action({"kind": "fail", "record": args.id, "label": label, "target": target,
                    "desc": desc, "error": res.get("error", "")})
        out({"ok": False, "error": res.get("error", "落库失败"), "snapshot": snap,
             "before": before, "after": after, "label": label}, 1)
    log_id = log_action({"kind": "apply", "record": args.id, "label": label, "target": target, "desc": desc,
                         "inverse": inverse_of(one.get("action", ""), target,
                                               one.get("content", ""), one.get("old_text", ""),
                                               res.get("lost_entry", "")),
                         "lost_entry": res.get("lost_entry", ""),
                         "snapshot": snap, "before": before.get(target), "after": after.get(target)})
    if args.index is None:
        archived = archive(args.id, "applied", {"payload": full, "result": res, "snapshot": snap})
        state = "整条已处理完，移入「已完成」"
    elif rest:
        write_ops(args.id, target, rest)
        archived = None
        state = f"这条还剩 {len(rest)} 处等你决定"
    else:
        archived = archive(args.id, "applied", {"payload": one, "result": res, "snapshot": snap})
        state = "最后一处也批了，整条移入「已完成」"
    out({"ok": True, "message": res.get("message", ""), "log_id": log_id, "snapshot": snap,
         "before": before, "after": after, "archived": archived, "state": state,
         "label": label, "desc": desc, "target": target})


def cmd_dryrun(args):
    payload = json.loads(args.payload) if args.payload else load_record(args.id)["payload"]
    if args.index is not None:
        payload = pick_op(payload, args.index)
    res, before, after, _ = run_payload(payload, dry=True)
    out({"ok": bool(res.get("success")), "message": res.get("message", ""), "error": res.get("error", ""),
         "lost_entry": res.get("lost_entry", ""), "action": payload.get("action", ""),
         "before": before, "after": after})


def cmd_drop(args):
    """不要：把某处（或整条）移进「已完成」，不写记忆。"""
    rec = load_record(args.id)
    full = rec["payload"]
    target = full.get("target", "memory")
    ops = rec_ops(full)
    if args.index is None:
        name = archive(args.id, "rejected", {"payload": full, "reason": args.reason})
        out({"ok": True, "state": "整条移入「已完成」", "archived": name})
    if not (0 <= args.index < len(ops)):
        out({"ok": False, "error": f"这条记录里没有第 {args.index + 1} 处改动"}, 1)
    dropped = ops[args.index]
    rest = ops[:args.index] + ops[args.index + 1:]
    desc = describe(dropped.get("action", ""), dropped.get("content", ""), dropped.get("old_text", ""))
    if rest:
        write_ops(args.id, target, rest)
        state = f"已丢掉第 {args.index + 1} 处，还剩 {len(rest)} 处"
        archived = None
        done_dir().mkdir(parents=True, exist_ok=True)
    else:
        archived = archive(args.id, "rejected", {"payload": dropped, "reason": args.reason})
        state = "最后一处也丢掉了，整条移入「已完成」"
    log_action({"kind": "drop", "record": args.id, "target": target, "desc": "丢弃：" + desc,
                "label": f"第 {args.index + 1} 处"})
    out({"ok": True, "state": state, "archived": archived, "desc": desc})


def cmd_memop(args):
    payload = {"action": args.action, "target": args.target,
               "content": args.content, "old_text": args.old_text}
    res, before, after, snap = run_payload(payload)
    desc = describe(args.action, args.content, args.old_text)
    if not res.get("success"):
        log_action({"kind": "fail", "target": args.target, "desc": desc, "error": res.get("error", "")})
        out({"ok": False, "error": res.get("error", "失败"), "snapshot": snap, "desc": desc}, 1)
    log_id = log_action({"kind": "memop", "target": args.target, "desc": desc, "inverse":
                         inverse_of(args.action, args.target, args.content, args.old_text,
                                    res.get("lost_entry", "")),
                         "lost_entry": res.get("lost_entry", ""),
                         "snapshot": snap, "before": before.get(args.target), "after": after.get(args.target)})
    out({"ok": True, "message": res.get("message", ""), "log_id": log_id, "snapshot": snap,
         "desc": desc, "before": before, "after": after, "lost_entry": res.get("lost_entry", ""),
         "target": args.target, "delta": len(args.content) - len(args.old_text)})


def harden_inverse(inv: dict, row: dict) -> tuple:
    """老式动作记录里的反向操作只有「旧文片段」—— 撤回会把那一整条其余的文字弄丢。

    Hermes 的 replace/remove 都是整条动作，所以正确的撤回必须用「原来那一整条」。
    新记录已经带 `lost_entry`；老记录（这个修复之前存下的）靠**当时那份快照**补全：
    在快照里找出这条旧文当时指向的那一整条。找不到就原样退回（宁可不动，也不乱写）。
    返回 (可能修正过的反向操作, 说明文字)。
    """
    act = inv.get("action")
    if act not in ("replace", "remove"):
        return inv, ""
    frag = (inv.get("content") or "").strip()
    snap = row.get("snapshot") or ""
    if not frag or not snap:
        return inv, ""
    try:
        d = snap_path(snap)
    except SystemExit:
        return inv, ""
    f = d / FILES_BY_TARGET.get(inv.get("target", "memory"), "MEMORY.md")
    if not f.exists():
        return inv, ""
    try:
        raw = f.read_text(encoding="utf-8")
    except OSError:
        return inv, ""
    entries = [e for e in (x.strip() for x in raw.split(ENTRY_SEP)) if e]
    exact = [e for e in entries if e == frag]
    hits = exact if exact else [e for e in entries if frag in e]
    if len(set(hits)) != 1 or hits[0] == frag:
        return inv, ""
    fixed = {**inv, "content": hits[0]}
    return fixed, "（已按当时快照补全被覆盖的那一整条）"


def cmd_undo(args):
    row = next((r for r in read_log(300) if r.get("log_id") == args.log_id), None)
    if not row:
        out({"ok": False, "error": "动作记录里找不到这一步"}, 1)
    inv = row.get("inverse")
    if not inv:
        out({"ok": False, "error": "这一步没有可撤回的反向操作（它本身就没写入成功）"}, 1)
    inv, hardened = harden_inverse(inv, row)
    res, before, after, snap = run_payload(inv)
    if not res.get("success"):
        out({"ok": False, "error": res.get("error", "撤回失败"), "snapshot": snap}, 1)
    log_action({"kind": "undo", "undone": args.log_id, "target": inv.get("target"), "snapshot": snap,
                "desc": "撤回：" + (row.get("desc") or "") + hardened,
                "before": before.get(inv.get("target")), "after": after.get(inv.get("target"))})
    out({"ok": True, "message": res.get("message", ""), "snapshot": snap, "before": before, "after": after,
         "hardened": bool(hardened), "undone": row.get("desc")})


def cmd_log(args):
    out({"ok": True, "entries": read_log(args.limit)})


def cmd_rollback(args):
    snap = snap_path(args.snapshot)
    if not snap.exists():
        out({"ok": False, "error": f"找不到快照 {args.snapshot}"}, 1)
    pf = snap / "profile.txt"
    snap_prof = pf.read_text(encoding="utf-8").strip() if pf.exists() else "default"
    if snap_prof != PROFILE:
        out({"ok": False, "error": f"这个快照属于档案「{snap_prof}」，不能用在「{PROFILE}」上"
                                   f"（否则会拿另一个档案的记忆盖掉这个档案）。先切换到那个档案再退。"}, 1)
    safety = snapshot("before-rollback")
    for f in FILES:
        src = snap / f
        if src.exists():
            shutil.copy2(src, memories_dir() / f)
    load_store, _ = hermes()
    out({"ok": True, "restored_from": args.snapshot, "safety_snapshot": safety,
         "usage": usage_of(load_store())})


def cmd_selfcheck(_a):
    checks = []

    def add(name, fn):
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    def c_read():
        load_store, _ = hermes()
        s = load_store()
        n = len(s._entries_for("memory")) + len(s._entries_for("user"))
        return n > 0, f"读到 {n} 条记忆，用量 {usage_of(s)}"

    def c_queue():
        n = len(list(pending_dir().glob("*.json"))) if pending_dir().exists() else 0
        return True, f"队列里 {n} 条待审"

    def c_dryrun():
        tmp = sandbox()
        try:
            os.environ["HERMES_HOME"] = tmp
            load_store, apply_pending = hermes()
            res = apply_pending({"action": "add", "target": "memory", "content": "selfcheck-probe"},
                                load_store())
            return bool(res.get("success")), "沙盒试跑通道正常"
        finally:
            os.environ["HERMES_HOME"] = str(HOME)
            shutil.rmtree(tmp, ignore_errors=True)

    def c_paths():
        snapshots_dir().mkdir(parents=True, exist_ok=True)
        done_dir().mkdir(parents=True, exist_ok=True)
        return True, f"快照与归档目录可写：{DATA_DIR}"

    add("档案信息", lambda: (True, f"当前档案 = {PROFILE}（{HOME}）"))
    add("能读到记忆文件", c_read)
    add("能读到待审队列", c_queue)
    add("试跑通道", c_dryrun)
    add("自己的目录可写", c_paths)
    all_ok = all(c["ok"] for c in checks)
    out({"ok": all_ok, "checks": checks,
         "verdict": "一切正常，跟当前 Hermes 版本还匹配" if all_ok else "有环节失配了 —— 看上面哪一条红"})


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("limits").set_defaults(fn=cmd_limits)

    p = sub.add_parser("apply")
    p.add_argument("id")
    p.add_argument("--index", type=int, default=None)
    p.add_argument("--payload")
    p.set_defaults(fn=cmd_apply)

    p = sub.add_parser("dryrun")
    p.add_argument("id", nargs="?")
    p.add_argument("--index", type=int, default=None)
    p.add_argument("--payload")
    p.set_defaults(fn=cmd_dryrun)

    p = sub.add_parser("drop")
    p.add_argument("id")
    p.add_argument("--index", type=int, default=None)
    p.add_argument("--reason", default="")
    p.set_defaults(fn=cmd_drop)

    p = sub.add_parser("memop")
    p.add_argument("--target", default="memory")
    p.add_argument("--action", required=True)
    p.add_argument("--content", default="")
    p.add_argument("--old-text", dest="old_text", default="")
    p.set_defaults(fn=cmd_memop)

    p = sub.add_parser("undo")
    p.add_argument("log_id")
    p.set_defaults(fn=cmd_undo)

    p = sub.add_parser("log")
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(fn=cmd_log)

    p = sub.add_parser("rollback")
    p.add_argument("snapshot")
    p.set_defaults(fn=cmd_rollback)

    sub.add_parser("selfcheck").set_defaults(fn=cmd_selfcheck)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
