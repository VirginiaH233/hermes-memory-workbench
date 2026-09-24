"""i18n.py —— 界面与提示文案的中英词典（唯一的一份）。

两个用途：
  · 页面（server.py 里的 JS）：把 EN 注入页面，页面用 T("中文") 查英文
  · 后台（ops.py / server.py 的提示与报错）：在序列化出口用 tr_obj() 翻字段

键就是**中文原文**；查找时空白折叠成一个空格再比（页面里的 NORM() 与这里的 norm() 一致），
所以多行、带缩进的长句也有干净的键。
带参数的句子：固定整句进 EN；带参数的进 RULES（中文里把参数写成 {}，英文里也用 {}）。

契约（由 i18ntest.py 机械验收）：
  · 页面里每条含中文的字符串都必须走 T("…")
  · 后台 Python 里每个含中文的字符串字面量（文档字符串除外）都必须在 EN 或 RULES 里
  · 英文值里不能出现中文
"""
import re

CJK = re.compile("[\u4e00-\u9fff]")


def norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


# ---------- 页面文案（server.py 里 T("…") 的键）----------
PAGE_EN = {
    "Hermes 记忆工作台": "Hermes Memory Workbench",
    "加载中…": "Loading…",
    "自检": "Self-check",
    "</b> 变成 <b>": " </b> to <b>",
    "</b>（不写入，只是预演）": "</b> (nothing is written — this is a dry run)",
    "</b>）还没有记忆 —— 多半是刚建好、Hermes 还没往里写过东西。 一旦写了，刷新一下这里就会出现。":
        "</b>) has no memory yet — it was probably just created and Hermes hasn't written to it. "
        "Once it does, refresh this page.",
    "<b>演示模式</b>：你看到的是一份假档案（假人物、假记忆）， 批准、改写、撤回随便点，"
    "<b>你的真实记忆一个字节都不会变</b>。 想回到自己的记忆：关掉窗口，用 <code>start.cmd</code> 重新打开。":
        "<b>Demo mode</b>: this is a fake profile (a made-up person with made-up memory). Approve, "
        "edit, undo — click anything; "
        "<b>your real memory will not change by a single byte</b>. To go back to your own memory, close "
        "this window and start again with <code>start.cmd</code>.",
    "<b>连不上本地服务。</b>": "<b>Can't reach the local service.</b>",
    "<br> 不满意就去「动作记录」点「撤回这一步」，只会还原这一处。":
        "<br>Not happy with it? Hit “Undo this step” in the action log — it restores only this change.",
    "<br>不满意就去「动作记录」点「撤回这一步」。":
        "<br>Not happy? Hit “Undo this step” in the action log.",
    "<br>记忆没有被改动。": "<br>Memory was not changed.",
    "<br>（这句旧文可能已被别处改过 —— 重新展开这条再试）":
        "<br>(that old text may have been changed elsewhere — collapse and reopen this entry, then retry)",
    "<div style=\"margin-top:6px\">这一步是较早记录的改动，撤回时按当时那份快照把<b>被覆盖的那一整条</b>"
    "补了回来（不会只剩旧文那几个字）。</div>":
        "<div style=\"margin-top:6px\">This is an older logged change: undo restored <b>the whole entry "
        "that had been overwritten</b> from the snapshot taken at the time.</div>",
    ">全部批准（": ">Approve all (",
    "」只负责定位。上面那一条里其余的文字会一起消失 —— 想留住它们，就把它们补进左边的框里。</div>":
        "” only locates it. Everything else in that entry disappears with it — add anything you want to "
        "keep to the box on the left.</div>",
    "」已经不在了（被删除或改名），已自动切回「": "” is gone (deleted or renamed). Switched back to “",
    "」档案的记忆 —— 不是平时聊天那个</span>": "” profile — not the one you normally chat in</span>",
    "」？ 只还原这一步，其他改动不受影响。": "”? Only this step is reverted; other changes are untouched.",
    "不能存成空的 —— 想删掉这条请用「删掉这条」": "Can't save an empty entry — use “Remove entry” to delete it",
    "丢掉第": "Discard change ",
    "会从 <b>": "goes from <b>",
    "你刚才看的档案「": "The profile you were viewing, “",
    "保存后立刻写进记忆（改前会自动存旧版）。确定？":
        "This writes to memory immediately (the previous version is snapshotted first). Continue?",
    "保存失败：": "Save failed: ",
    "保存失败：不写就什么都不影响": "Save failed — nothing was written, so nothing changed",
    "先写点内容": "Write something first",
    "写入需批准：<b>读不到配置</b> —— 检查这个档案 <code>config.yaml</code> 里的 <code>memory.write_approval</code>。":
        "Ask before writing memory: <b>can't read the config</b> — check <code>memory.write_approval</code> "
        "in this profile's <code>config.yaml</code>.",
    "写入需批准：<b>已开启</b> —— 系统想改记忆时会先来这里排队等你点头。":
        "Ask before writing memory: <b>on</b> — when the agent wants to change memory it queues here and "
        "waits for your approval.",
    "写入需批准：<b>还没开</b> —— 没开的话系统会直接改记忆、不问你。<br> 想开：在聊天里输入 "
    "<code>/memory approval on</code>（写在哪个档案就管哪个档案）。":
        "Ask before writing memory: <b>off</b> — without it the agent writes memory directly, without "
        "asking.<br> To turn it on, type <code>/memory approval on</code> in the chat (it applies to the "
        "active profile).",
    "出错了：": "Error: ",
    "切到档案": "Switched to profile ",
    "删掉整条": "Remove entry",
    "后台复盘": "Background review",
    "和现在一模一样，不用保存": "Identical to what's stored — nothing to save",
    "处改动</span>": " changes</span>",
    "处现在落不了地</span>": " can't be applied</span>",
    "处（": " (",
    "处？ （不写进记忆，会收进「已完成」留档）":
        " changes? (Nothing is written to memory; the item is archived under “done”.)",
    "失败：": "Failed: ",
    "字": " chars",
    "字 ｜ 只在本机跑": " chars | local only",
    "字 ｜ 用户画像": " chars | User profile ",
    "字数 <b>": "Characters <b>",
    "字数：<b>": "Characters: <b>",
    "字（": " chars (",
    "展开改": "Edit",
    "已丢掉": "Discarded",
    "已丢掉这一处（记忆没动）": "Change discarded (memory untouched)",
    "已保存 ✅": "Saved ✅",
    "已写进记忆 ✅": "Written to memory ✅",
    "已删除": "Removed",
    "已删除 ✅ 可去「动作记录」撤回": "Removed ✅ — you can undo it in the action log",
    "已加进去": "Added",
    "已加进去 ✅ 现在": "Added ✅ now ",
    "已复制，粘到聊天里发给我就行": "Copied — paste it into the chat and send it to me",
    "已撤回 ✅": "Undone ✅",
    "已撤回 ✅ 现在是": "Undone ✅ now ",
    "已撤回 ✅（按快照补全了整条）": "Undone ✅ (the whole entry was restored from the snapshot)",
    "已收进「已完成」": "Archived under “done”",
    "已显示在卡片上 —— 手动选中复制也行": "Shown on the card — you can also select and copy it manually",
    "帮我改待审提议": "Please edit pending proposal ",
    "待审提议": "Pending proposals",
    "全部记忆": "All memory",
    "动作记录": "Action log",
    "<div class=\"empty\">连不上本地服务 —— 请双击 <code>start.cmd</code> 重新启动。</div>":
        "<div class=\"empty\">Can't reach the local service — double-click <code>start.cmd</code> "
        "to start it again.</div>",
    "<span class=\"meta\" style=\"align-self:center\">档案：</span>":
        "<span class=\"meta\" style=\"align-self:center\">Profile: </span>",
    "我的笔记": "Notes",
    "我的笔记 MEMORY.md": "Notes (MEMORY.md)",
    "我（聊天中）": "Me (in chat)",
    "找不到任何档案 —— 检查 Hermes 是不是装在这里、或这个档案是不是被删了。":
        "No profiles found — check that Hermes is installed here, or whether this profile was deleted.",
    "撤回失败：": "Undo failed: ",
    "撤回我在这份文件上最近一次改动？": "Undo the most recent change to this file?",
    "撤回这一步：「": "Undo this step: “",
    "收起": "Collapse",
    "整条已写进记忆 ✅": "Whole entry written to memory ✅",
    "整条替换": "Replace whole entry",
    "整条都不要？ （不写进记忆，会收进「已完成」留档）":
        "Discard the whole item? (Nothing is written to memory; it's archived under “done”.)",
    "新增一条": "Add entry",
    "服务未连接": "Service not reachable",
    "服务返回了看不懂的内容（HTTP": "The service returned something unexpected (HTTP ",
    "未知错误": "Unknown error",
    "条": " entries",
    "条</span></div>": " entries</span></div>",
    "条含失效项</div>": " contain stale changes</div>",
    "条待审</span>": " pending</span>",
    "档案": "Profile ",
    "没写进去，记忆是安全的": "Nothing was written — memory is safe",
    "没有保存 ❌": "Not saved ❌ ",
    "没有写入 —— 记忆一个字都没动 ❌": "Nothing written — memory is untouched ❌ ",
    "没有写入 —— 记忆一个字都没动 ❌<br>": "Nothing written — memory is untouched ❌<br>",
    "没有删除 ❌": "Not removed ❌ ",
    "没有加进去 ❌": "Not added ❌ ",
    "演示档案（假数据，跟你的真实记忆无关）": "Demo profile (fake data, unrelated to your real memory)",
    "用户画像": "User profile",
    "用户画像 USER.md": "User profile (USER.md)",
    "确定删掉这条？": "Remove this entry?",
    "第": "Change ",
    "自检中…": "Self-checking…",
    "草稿已保存 —— 还没写进记忆（记忆一个字没动）":
        "Draft saved — not written to memory yet (memory untouched)",
    "草稿已保存（记忆没动）": "Draft saved (memory untouched)",
    "试跑不通过 ❌": "Dry run failed ❌ ",
    "试跑中…": "Dry-running…",
    "试跑通过 ✅ 这一处写进去后，": "Dry run passed ✅ After this change, ",
    "这一整条会被删掉": "this whole entry will be deleted",
    "这一整条会被新内容覆盖": "this whole entry will be overwritten",
    "这个档案（<b>": "This profile (<b>",
    "这份文件最近没有可撤回的改动": "No recent change to undo for this file",
    "这条已经不在队列里了 —— 页面正在刷新": "This item is no longer in the queue — refreshing",
    "连不上服务，页面显示的是上一次读到的内容": "Can't reach the service — showing the last data loaded",
    "连不上本地服务（没连上就没写入，记忆是安全的）—— 重新双击 start.cmd 再试。":
        "Can't reach the local service (nothing was written — memory is safe). Start it again with start.cmd.",
    "那个黑窗口可能被关了 —— 重新双击 start.cmd 就好，你改的东西没有丢。":
        "That console window may have been closed — just start it again with start.cmd; your edits are not lost.",
    "（读的是它自己的记忆）": " (its own memory)",
    "） <br>不满意点下面的「改回我刚保存前的样子」，或去「动作记录」撤回。":
        ") <br>Not happy? Use “revert to what I saved before” below, or undo it in the action log.",
    "）：改成": "): becomes ",
    "，匹配": ", matching ",
    "｜ 我的笔记": " | Notes ",
}

# ---------- 后台文案（ops.py / server.py 的提示、横幅、自检）----------
BACKEND_EN = {
    "一切正常，跟当前 Hermes 版本还匹配": "All good — matches your current Hermes version",
    "一条都不剩了 —— 用「不要这一处」把它们逐条丢掉":
        "Nothing left — use “Discard this change” to drop them one by one",
    "动作记录里找不到这一步": "That step isn't in the action log",
    "找不到 Hermes 源码目录 —— 设一下环境变量 MR_AGENT_DIR 指向 hermes-agent 目录":
        "Can't find the Hermes source directory — set MR_AGENT_DIR to your hermes-agent folder",
    "整条移入「已完成」": "The whole item was moved to “done”",
    "整条已处理完，移入「已完成」": "The whole item is done — moved to “done”",
    "最后一处也批了，整条移入「已完成」": "That was the last change — the item moved to “done”",
    "最后一处也丢掉了，整条移入「已完成」": "That was the last change — the item moved to “done”",
    "沙盒试跑通道正常": "sandbox dry-run path works",
    "有环节失配了 —— 看上面哪一条红": "Something doesn't match — see which line is red above",
    "这一步没有可撤回的反向操作（它本身就没写入成功）":
        "This step has nothing to undo (it never wrote anything)",
    "这条记录已经不在了（可能已在别处处理）": "That item is gone (it may have been handled elsewhere)",
    "拒绝：令牌不对（页面可能没刷新，Ctrl+R 一下）":
        "Refused: wrong token (the page may be stale — press Ctrl+R)",
    "拒绝：只接受 application/json": "Refused: only application/json is accepted",
    "拒绝：请求太大": "Refused: request too large",
    "拒绝：请求来源不是本机页面": "Refused: the request didn't come from this page on this machine",
    "操作超时": "The operation timed out",
    "★ 演示模式：用的是演示档案（假数据），你的真实记忆不会被碰。":
        "★ Demo mode: a demo profile (fake data). Your real memory will not be touched.",
    "（关掉这个窗口就是关掉它；它不改 Hermes 任何东西）":
        "(Closing this window stops it. It doesn't change anything in Hermes.)",
    "已停止。": "Stopped.",
    "启动自检：通过（读记忆 / 队列 / 沙盒试跑 都正常）":
        "Startup self-check: passed (memory / queue / sandbox dry run all fine)",
    "启动自检：有问题 —— 页面上会红字提示，未修好前不要批准任何提议：":
        "Startup self-check: problems found — the page shows them in red; don't approve anything until fixed:",
    # 自检的条目名（页面上红字列表用）
    "能读到记忆文件": "Can read the memory files",
    "能读到待审队列": "Can read the pending queue",
    "试跑通道": "Sandbox dry-run path",
    "自己的目录可写": "Its own folder is writable",
    "自检没有返回结果": "The self-check returned nothing",
    "可以点一下页面的「自检」再看一遍": "Hit “Self-check” on the page to check again",
    # 自检条目名（改名为「档案信息」，避免与页面上的「档案」混淆）
    "档案信息": "Profile info",
    # 后台报错 / 控制台（--help 与横幅也跟着系统区域走）
    "ops.py 没有任何输出": "ops.py produced no output",
    "失败": "Failed",
    "撤回失败": "Undo failed",
    "落库失败": "The write failed",
    "记录编号": "record id",
    "快照名": "snapshot name",
    "丢弃：": "Discard: ",
    "撤回：": "Undo: ",
    "端口": "port",
    "记忆审阅台 —— 看、改、批、撤 Hermes 的记忆（本地页面）":
        "Memory Workbench — see, edit, approve and undo Hermes memory (local page)",
    "用演示数据启动（假档案，跟你的真实记忆完全隔离）":
        "start with demo data (a fake profile, fully isolated from your real memory)",
    "重建演示数据（配合 --demo）": "rebuild the demo data (used with --demo)",
    # 批准前的检查（哪句旧文能不能对上）
    "这段原文已经不在文件里 —— 批准会失败":
        "This old text is no longer in the file — approving would fail",
    "这句旧文已经找不到了（多半被后来的写入换掉过）—— 去「全部记忆」里挑一句现在还在的":
        "That old text is no longer in the file (a later write probably replaced it) — "
        "pick a line that's still there from “All memory”",
    "这段旧文能对上好几条不同的记忆 —— 系统无法确定改哪一条，把旧文写成完整的那一条":
        "This old text matches several different entries — the system can't tell which one to "
        "change; make the old text the full entry",
    "（已按当时快照补全被覆盖的那一整条）":
        " (the whole overwritten entry was restored from the snapshot taken at the time)",
}

# ---------- 带参数的句子：中文模板（{} 占位）→ 英文模板 ----------
RULES = {
    "队列里找不到记录 {}（可能已在别处处理）":
        "Record {} isn't in the queue (it may have been handled elsewhere)",
    "{}不合法：{}（只允许字母、数字、- 和 _，64 字以内）":
        "Invalid {}: {} (letters, digits, - and _ only, up to 64 characters)",
    "{}不合法（越出目录）": "Invalid {} (it escapes the directory)",
    "这条记录里没有第 {} 处改动": "This record has no change #{}",
    "找不到快照 {}": "Snapshot {} not found",
    "找不到档案「{}」—— 它可能被删除或改名了。已停在这里，没有显示别的档案的记忆。":
        "Profile “{}” not found — it may have been deleted or renamed. Nothing else was shown instead.",
    "找不到档案「{}」—— 可能被删除或改名了，这一步没有执行任何操作。":
        "Profile “{}” not found — it may have been deleted or renamed. Nothing was executed.",
    "这个快照属于档案「{}」，不能用在「{}」上（否则会拿另一个档案的记忆盖掉这个档案）。先切换到那个档案再退。":
        "This snapshot belongs to profile “{}” and can't be applied to “{}” (it would overwrite this "
        "profile's memory with another one's). Switch to that profile first, then roll back.",
    "未知接口 {}": "Unknown endpoint {}",
    "第 {} 处": "Change {}",
    "整条（{} 处）": "Whole item ({} changes)",
    "装不上 Hermes 的记忆模块（{}）—— 你的 Hermes 版本可能不兼容，或者 MR_AGENT_DIR 指错了：{}":
        "Couldn't load Hermes' memory module ({}) — your Hermes version may be incompatible, or "
        "MR_AGENT_DIR points to the wrong place: {}",
    "ops.py 输出无法解析：{}": "Couldn't parse ops.py output: {}",
    "找不到 Python（{}）—— 用 start.cmd / start.sh 启动它":
        "Can't find Python ({}) — start it with start.cmd / start.sh",
    "新增「{}」": "Added “{}”",
    "删除整条「{}」（旧文用来定位是哪一条）":
        "Removed the whole entry “{}” (the old text was only used to locate it)",
    "整条替换「{}」→「{}」": "Replaced the whole entry “{}” → “{}”",
    "丢弃：{}": "Discarded: {}",
    "撤回：{}": "Undid: {}",
    "记忆审阅台已启动：{}": "Hermes Memory Workbench running at {}",
    "演示档案位置：{}": "Demo profile folder: {}",
    "启动自检失败（不影响页面浏览）：{}": "Startup self-check failed (browsing still works): {}",
    "这条还剩 {} 处等你决定": "{} more change(s) waiting for your decision",
    "已丢掉第 {} 处，还剩 {} 处": "Discarded change #{}; {} left",
    "读到 {} 条记忆，用量 {}": "read {} entries, usage {}",
    "队列里 {} 条待审": "{} item(s) pending",
    "读到了 {} 条记忆": "read {} entries",
    "快照与归档目录可写：{}": "snapshots and archive folders are writable: {}",
    "当前档案 = {}（{}）": "current profile = {} ({})",
    "（原文只有片段，已按当时快照补全整条）":
        " (the log only had a fragment — the whole entry was restored from the snapshot taken at the time)",
    "（找不到当时的快照，按原样退回）": " (no snapshot from that time — left as is)",
}

EN = {}
EN.update(PAGE_EN)
EN.update(BACKEND_EN)


def t(s: str, lang: str = "zh", *args, **vars) -> str:
    """把一条中文文案换成目标语言；缺词条就原样返回（中文兜底）。参数支持 {} 或 {name}。"""
    out = s if lang != "en" else EN.get(norm(s), s)
    if args or vars:
        try:
            out = out.format(*args, **vars)
        except (KeyError, IndexError):
            pass
    return out


def tr(s: str, lang: str = "zh", _depth: int = 0) -> str:
    """翻译一条**已经渲染好**的后台文案：先精确匹配，再试带参数的规则（两层，够嵌套用）。"""
    if lang != "en" or not s or _depth > 2:
        return s
    key = norm(s)
    if key in EN:
        return EN[key]
    for k, v in RULES.items():
        parts = k.split("{}")
        if len(parts) < 2:
            continue
        rx = "^" + "(.+?)".join(re.escape(p) for p in parts) + "$"
        m = re.match(rx, key, re.S)
        if m:
            filled = v.format(*[g.strip() for g in m.groups()])
            return tr(filled, lang, _depth + 1)      # 里面还嵌着中文（如「撤回：新增「X」」）再翻一层
    return s


TR_FIELDS = ("error", "desc", "state", "label", "message", "detail", "name", "verdict", "note")


def tr_obj(d, lang: str = "zh"):
    """序列化出口用：把响应里会显示给用户的字段翻一遍（列表/嵌套也走）。"""
    if lang != "en":
        return d
    if isinstance(d, dict):
        return {k: (tr(v, lang) if k in TR_FIELDS and isinstance(v, str) else tr_obj(v, lang))
                for k, v in d.items()}
    if isinstance(d, list):
        return [tr_obj(x, lang) for x in d]
    return d


def resolve_lang(accept: str = "", fallback: str = "zh") -> str:
    """按浏览器语言：出现 zh 就是中文，否则英文（拿不到头信息时按 fallback）。"""
    a = (accept or "").lower()
    if not a.strip():
        return fallback
    if a.startswith("zh") or ",zh" in a or " zh" in a:
        return "zh"
    return "en"


def console_lang() -> str:
    """终端横幅用哪种语言：优先 MR_LANG，其次系统区域（海外用户看到英文横幅）。"""
    import os
    env = (os.environ.get("MR_LANG") or "").strip()
    if env in ("zh", "en"):
        return env
    try:
        import locale
        loc = (locale.getlocale()[0] or "") + (locale.getdefaultlocale()[0] or "")
    except Exception:
        loc = ""
    return "zh" if "zh" in loc.lower() or "chinese" in loc.lower() else "en"

# ---- 重包后的补充词条（按文字节点包装产生的短词条）----
EN.update({
    '+ 在末尾新增一条': '+ Add an entry at the end',
    '不要这一处': 'Discard this change',
    '试跑这一处': 'Dry-run this change',
    '批准这一处（写进记忆）': 'Approve this change (writes to memory)',
    '保存草稿（先不写）': 'Save draft (no write)',
    '全部批准（': 'Approve all (all ',
    '处一起写进）': ' together)',
    '复制给 Hermes 的指令': 'Copy the instruction for Hermes',
    '整条都不要': 'Discard the whole item',
    '给我看 / 在这里改': 'Preview / edit here',
    '真正写进系统的那一行（只读）': 'The exact line that gets written (read-only)',
    '（旧文只用来找到它，不是改那几个字）：': "(the old text only finds the entry — it isn't what gets changed):",
    '都能落地': 'All applicable',
    '处现在落不了地': " can't be applied right now",
    '有失效项 —— 整条一起批会失败，先逐处处理': 'has stale changes — approving the whole item would fail; handle them one by one',
    '这处现在落不了地 —— 看上面的原因': "this change can't be applied right now — see the reason above",
    '这处落不了地，原因就是上面那条。「批准」已经先关掉了，所以你点不出错。 你可以：① 点「不要这一处」把它丢掉；② 真想改这条 —— 点卡片下方的 「复制给 Hermes 的指令」发给我，我帮你把「旧文」换成现在文件里真正的那句。': "This change can't be applied — the reason is above. “Approve” is already off, so you can't click into an error. You can: ① hit “Discard this change” to drop it; ② if you really want this change, hit “Copy the instruction for Hermes” at the bottom of the card and send it to me — I'll swap the “old text” for the line that's actually in the file now.",
    '这一步会把这一整条覆盖掉：': 'This step overwrites the whole entry: ',
    '会从': 'goes from ',
    '变成': 'becomes ',
    '处改动': ' change(s)',
    '处': ' change(s)',
    '条待审': ' pending',
    '字数': 'Chars',
    '字数：': 'Chars: ',
    '用了': 'used ',
    '（不写入，只是预演）': '(nothing is written — this is a dry run)',
    '（这句旧文可能已被别处改过 —— 重新展开这条再试）': '(that old text may have been changed elsewhere — collapse and reopen this entry to retry)',
    '记忆没有被改动。': 'Memory was not changed.',
    '不满意就去「动作记录」点「撤回这一步」。': 'Not happy? Use “Undo this step” in the action log.',
    '不满意就去「动作记录」点「撤回这一步」，只会还原这一处。': 'Not happy? Use “Undo this step” in the action log — it restores only this change.',
    '撤回这一步': 'Undo this step',
    '撤回这份文件最近一次改动': 'Undo the last change to this file',
    '不满意点下面的「改回我刚保存前的样子」，或去「动作记录」撤回。': 'Not happy? Use “revert to what I saved before” below, or undo it in the action log.',
    '队列是空的 —— 这是正常状态': "The queue is empty — that's normal",
    '只有「系统想改记忆」和「写入需批准已开」两件事同时成立，这里才会有东西。': 'Items appear here only when two things are true: the system wants to change memory, and write-approval is on.',
    '想马上看它工作起来：': 'To see it work right now:',
    '回到聊天，让 Hermes 记住一件事（比如「记住我对花生过敏」）': "Go back to the chat and have Hermes remember something (say, “remember I'm allergic to peanuts”)",
    '它想记的时候会被拦住 —— 这里就会出现一条待审提议': "When it tries, it's held back — a pending proposal shows up here",
    '回来批准 / 改写 / 丢弃；想反悔就点撤回，记忆能回到原样': 'Come back here to approve / edit / discard; if you change your mind, undo puts memory back',
    '想先看它长什么样：': 'Want to see what it looks like first:',
    '（假档案，跟你的真实记忆完全隔离） —— 也可以点上面的「自检」按钮看这台机器的读写通道通不通。': "(a fake profile, fully isolated from your real memory) — you can also hit “Self-check” above to see whether this machine's read/write paths work.",
    '一个 ID 里可能有好几处改动，可以分开处理。': 'One item can hold several changes, and you can handle them one by one. ',
    '想一次全批就点卡片底部的「全部批准」； 只想批其中一处，就点那一处自己的「批准这一处」。': "To approve everything at once, use “Approve all” at the bottom of the card; to approve just one, use that change's own “Approve this change”.",
    '改文字': 'Editing',
    '：直接在左边的框里打字，右边是真正写进系统的那一行（跟着变、字数实时）； 改完可以点「保存草稿」，也可以直接点「批准」（会先存再批）。': ": just type in the left box; the right side shows the line that will actually be written (updating live, with the character count). When you're done you can hit “Save draft”, or hit “Approve” directly (it saves first, then approves).",
    '只有「批准」会写进 MEMORY.md / USER.md': 'Only “Approve” writes to MEMORY.md / USER.md',
    '，其余动作只动队列。': '; everything else only touches the queue.',
    '：写进去的是左边框里的完整内容， 「': ': what gets written is the whole content of the left box, and the “',
    '」只负责定位。上面那一条里其余的文字会一起消失 —— 想留住它们，就把它们补进左边的框里。': '” only locates the entry. Everything else in that line disappears too — add whatever you want to keep to the box on the left.',
    '这里是现在全部的记忆，这是唯一的编辑入口。': 'This is all of your memory — and the only place to edit it.',
    '用下面两个页签在「我的笔记」和「用户画像」之间切换； 点某一条的「展开改」就能改，右边实时显示真正写进系统的那一行，保存后立刻生效。 改前自动存旧版，不满意就去「动作记录」点「撤回」。': "Use the two tabs below to switch between “Notes” and “User profile”; hit “Edit” on an entry to change it — the right side shows the line that will actually be written, and saving takes effect immediately. The old version is snapshotted first, so if you're not happy, undo it in the action log.",
    '搜索': 'Search',
    '清空': 'Clear',
    '在「': 'Search “',
    '」里搜字…': '”…',
    '现在文件里是：': 'Currently in the file: ',
    '保存这条（立刻生效）': 'Save entry (takes effect now)',
    '加进去（立刻生效）': 'Add entry (takes effect now)',
    '新的一条（给我看 / 在这里写）': 'New entry (preview / write here)',
    '取消': 'Cancel',
    '删掉这条': 'Delete entry',
    '你已改过': 'You edited this',
    '重试': 'Retry',
    '每一次写进记忆的动作都记在这里': 'Every action that wrote to memory is recorded here',
    '，带字数变化。点「撤回这一步」就精确还原那一步 —— 只动它碰过的那条，不影响你之后做的其他改动。': ', with the character-count change. “Undo this step” restores exactly that step — it only touches the entry it changed and leaves your later edits alone.',
    '还没有动作。做过一次批准/保存后，这里就有记录。': "Nothing yet. After one approve/save there'll be a record here.",
    '写入需批准：': 'Approval required before writing: ',
    '读不到配置': "can't read the config",
    '—— 检查这个档案': ' — check ',
    '里的': "'s ",
    '已开启': 'On',
    '还没开': 'Off',
    '—— 没开的话系统会直接改记忆、不问你。': ' — with it off, the system changes memory directly without asking you.',
    '—— 系统想改记忆时会先来这里排队等你点头。': ' — when the system wants to change memory it queues here and waits for your go-ahead.',
    '（写在哪个档案就管哪个档案）。': " (whichever profile you're in is the memory you're managing).",
    '想开：在聊天里输入': 'To turn it on, type this in the chat: ',
    '把下面这段发给我（Hermes）就行：': 'Just send me (Hermes) the text below: ',
    '你正在看的是「': "You're viewing the “",
    '」档案的记忆 —— 不是平时聊天那个': '” profile — not the one you usually chat in',
    '这个档案（': 'This profile (',
    '⚠️ 这是': '⚠️ This is ',
    '）还没有记忆 —— 多半是刚建好、Hermes 还没往里写过东西。 一旦写了，刷新一下这里就会出现。': ") has no memory yet — it was probably just created and Hermes hasn't written to it. Once it does, refresh this page.",
    '⚠ 启动自检没通过 —— 修好之前先别批准任何提议': "⚠ Startup self-check failed — don't approve anything until it's fixed",
    '批准不会硬写：通道不通它会明确报错、记忆保持原样。下面是哪一项不通：': "Approving never force-writes: if a path is broken it says so and your memory stays as it was. Here's what's broken:",
    '改完配置或装好 Hermes 后，点页面右上角的「自检」重新检查一遍。': 'After fixing the config or installing Hermes, hit “Self-check” at the top right to re-check.',
    '连不上本地服务。': "Can't reach the local service.",
    '演示模式': 'Demo mode',
    '：你看到的是一份假档案（假人物、假记忆）， 批准、改写、撤回随便点，': ': this is a fake profile (a made-up person with made-up memory). Approve, edit, undo — click anything; ',
    '你的真实记忆一个字节都不会变': "your real memory won't change by a single byte",
    '。 想回到自己的记忆：关掉窗口，用': '. To go back to your own memory: close this window and ',
    '重新打开。': 'start again.',
    '⚠ 其中': '⚠ ',
    '条含失效项': ' stale change(s)',
})
