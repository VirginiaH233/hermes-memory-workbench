#!/usr/bin/env python3
"""demo.py —— 「演示档案」：给第一次打开的人一份假数据，用来学会这个工具。

为什么要有它：新装的人看到的是一条空队列，空队列教不了任何东西。
但演示数据**绝不能碰真实记忆**，所以这里是一整套隔离的东西：

    demo-home/
      config.yaml            假的配置（只为让字数上限能显示）
      memories/MEMORY.md     假的「我的笔记」
      memories/USER.md       假的「用户画像」
      pending/memory/*.json  4 条假待审提议（覆盖各种情况）
      data/oplog.jsonl       演示模式的动作记录（不写进真目录）
      data/snapshots/        演示模式的快照
      data/done/             演示模式的归档

启动时配合 MR_HOME / MR_DATA_DIR 指到这里，ops.py 与 server.py 都只看这两个变量 ——
所以演示模式下你就算把每条都批准一遍，真实记忆也**一个字节都不会变**。

假数据里的人中文版叫「阿岸」、英文版叫 Alex，都是编出来的（谁都不认识），免得被误当成真事。
用哪种语言由 MR_LANG 决定（没给就跟着系统区域，与终端横幅同一套判断）。
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

DELIM = "\n§\n"
DEMO_HOME = Path(__file__).resolve().parent / "demo-home"

_CONFIG = """# 演示档案的假配置 —— 只为让页面的字数上限显示出来。
memory:
  memory_enabled: true
  user_profile_enabled: true
  memory_char_limit: 2500
  user_char_limit: 2000
  write_approval: true
"""

# ---- 假的「我的笔记」（6 条）----
MEMORY_ZH = [
    "阿岸是自由职业的产品顾问，主要帮小团队梳理需求、写 PRD，用 Python 和 Figma。",
    "工作习惯：上午 9 点到 11 点不安排会议，这段时间用来写东西。",
    "★ 阿岸讨厌「发布会腔」的文案 —— 对外写东西要像人说话，标题一眼看得懂。",
    "正在做一个给独立开发者用的记账小工具，项目代号「贝壳」，还在验证阶段。",
    "阿岸的电脑是 Windows 11，主力编辑器是 VS Code，常用快捷键 Ctrl+Shift+P。",
    "沟通偏好：要要点式的短回答，不要长篇铺垫；先给结论再给理由。",
]
MEMORY_EN = [
    "Alex is a freelance product consultant who helps small teams shape requirements and write "
    "PRDs; works in Python and Figma.",
    "Work habit: no meetings between 9 and 11 a.m. — that block is for writing.",
    "★ Alex hates launch-event copy — anything external should sound like a person talking, with "
    "a headline you get at a glance.",
    "Building a small bookkeeping tool for indie developers, codename \"Shell\" — still in "
    "validation.",
    "Alex's machine is Windows 11, main editor is VS Code, most-used shortcut Ctrl+Shift+P.",
    "Communication preference: short bullet-point answers, no long wind-ups; conclusion first, "
    "then reasons.",
]

# ---- 假的「用户画像」（4 条）----
USER_ZH = [
    "独立开发者 / 产品顾问，中文母语，日常英文读写没问题。",
    "决策习惯：喜欢先看到两个方案再拍板，不喜欢被直接推一个结论。",
    "在意数据安全：任何工具都要能随时删掉、不能偷偷联网。",
    "业余爱好：周末爬山、做手冲咖啡。",
]
USER_EN = [
    "Indie developer / product consultant, native English speaker.",
    "Decision style: likes to see two options before committing; dislikes being pushed a single "
    "conclusion.",
    "Cares about data safety: any tool must be deletable at any time, and must not phone home.",
    "Hobbies: hiking on weekends, pour-over coffee.",
]


def _record(rid: str, summary: str, payload: dict, minutes_ago: int = 5) -> dict:
    """一条待审提议，字段与 Hermes 自己写的完全一致。"""
    return {"id": rid, "subsystem": "memory", "action": payload.get("action", "add"),
            "summary": summary, "origin": "background_review",
            "created_at": time.time() - minutes_ago * 60,
            "payload": payload}


def _records_zh() -> list:
    """4 条演示提议：新增 / 改写 / 一处一批 / 已经失效的改写。

    最后一条是故意做的「坏例子」——让你看到工具怎么提示「这句旧文已经找不到了」。
    """
    return [
        _record("demo0001",
                "阿岸提到下周要去杭州出差三天，顺便约了老朋友见面。",
                {"action": "add", "target": "memory",
                 "content": "下周要去杭州出差三天（周二到周四），顺便约了老朋友见面。"},
                minutes_ago=3),
        _record("demo0002",
                "阿岸说记账工具「贝壳」已经砍掉了多账户功能，只保留单账户记账。",
                {"action": "replace", "target": "memory",
                 "old_text": "还在验证阶段",
                 "content": "已经砍掉多账户功能，只保留单账户记账，正在做第一批内测。"},
                minutes_ago=9),
        _record("demo0003",
                "阿岸这轮聊到两件事：编辑器换了、周末安排有变化。",
                {"action": "batch", "target": "memory",
                 "operations": [
                     {"action": "replace",
                      "old_text": "阿岸的电脑是 Windows 11，主力编辑器是 VS Code，常用快捷键 Ctrl+Shift+P。",
                      "content": "阿岸的电脑是 Windows 11，主力编辑器换成了 Zed，VS Code 只留着跑调试。"},
                     {"action": "add",
                      "content": "最近在学手冲咖啡，喜欢浅烘焙的耶加雪菲。"},
                 ]},
                minutes_ago=16),
        _record("demo0004",
                "「这句旧文已经不存在了」的坏例子：让你看清失效的提议长什么样。",
                {"action": "replace", "target": "user",
                 "old_text": "爱好是摄影和骑行",
                 "content": "业余爱好：周末爬山、做手冲咖啡、偶尔拍胶片。"},
                minutes_ago=25),
    ]


def _records_en() -> list:
    """Same four cases in English: an add, a rewrite, a batch, and a stale one."""
    return [
        _record("demo0001",
                "Alex mentioned a three-day work trip to Chicago next week, and meeting an old "
                "friend while there.",
                {"action": "add", "target": "memory",
                 "content": "Flying to Chicago next week for three days (Tue–Thu), and meeting an "
                            "old friend while there."},
                minutes_ago=3),
        _record("demo0002",
                "Alex said the bookkeeping tool \"Shell\" has dropped multi-account support — "
                "single-account only now.",
                {"action": "replace", "target": "memory",
                 "old_text": "still in validation",
                 "content": "Dropped multi-account support — single-account bookkeeping only, "
                            "first beta testers are trying it now."},
                minutes_ago=9),
        _record("demo0003",
                "Alex mentioned two things this round: a new editor, and a weekend change.",
                {"action": "batch", "target": "memory",
                 "operations": [
                     {"action": "replace",
                      "old_text": "Alex's machine is Windows 11, main editor is VS Code, "
                                   "most-used shortcut Ctrl+Shift+P.",
                      "content": "Alex's machine is Windows 11; the main editor is now Zed, with "
                                 "VS Code kept only for debugging."},
                     {"action": "add",
                      "content": "Recently learning pour-over coffee — likes light-roast "
                                 "Yirgacheffe."},
                 ]},
                minutes_ago=16),
        _record("demo0004",
                "The \"this old text no longer exists\" example: shows what a stale proposal "
                "looks like.",
                {"action": "replace", "target": "user",
                 "old_text": "hobbies are photography and cycling",
                 "content": "Hobbies: hiking on weekends, pour-over coffee, occasional film "
                            "photography."},
                minutes_ago=25),
    ]


def demo_lang() -> str:
    """演示数据用哪种语言：MR_LANG 优先，否则跟着系统区域。"""
    import i18n
    forced = (os.environ.get("MR_LANG") or "").strip().lower()
    if forced in ("zh", "en"):
        return forced
    return i18n.console_lang()


def ensure_demo_home(reset: bool = False, lang: str = "") -> Path:
    """造出（或重置）演示档案，返回它的家目录。"""
    lang = lang or demo_lang()
    memory = MEMORY_EN if lang == "en" else MEMORY_ZH
    user = USER_EN if lang == "en" else USER_ZH
    records = _records_en() if lang == "en" else _records_zh()

    home = DEMO_HOME
    if reset and home.exists():
        shutil.rmtree(home, ignore_errors=True)
    (home / "memories").mkdir(parents=True, exist_ok=True)
    (home / "pending" / "memory").mkdir(parents=True, exist_ok=True)
    (home / "data" / "snapshots").mkdir(parents=True, exist_ok=True)
    (home / "data" / "done").mkdir(parents=True, exist_ok=True)

    (home / "config.yaml").write_text(_CONFIG, encoding="utf-8")
    (home / "memories" / "MEMORY.md").write_text(DELIM.join(memory) + "\n", encoding="utf-8")
    (home / "memories" / "USER.md").write_text(DELIM.join(user) + "\n", encoding="utf-8")

    qdir = home / "pending" / "memory"
    for old in qdir.glob("*.json"):
        old.unlink()
    for rec in records:
        (qdir / f"{rec['id']}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return home


if __name__ == "__main__":
    import sys
    p = ensure_demo_home(reset="--reset" in sys.argv)
    print(f"演示档案已就绪：{p}")
