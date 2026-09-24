"""i18ntest.py —— 双语的机械验收（不靠肉眼）。

契约：
  1. 页面 JS 里**每条含中文的字符串**都必须走 T("…")，否则英文模式下会冒出中文
  2. HTML 骨架里的中文只允许出现在 <title>/<h1>/#sub（这三处由 JS 覆盖），别处不许有
  3. 后台（ops.py / server.py 的 Python 部分）**每个含中文的字符串字面量**（文档字符串除外）
     都必须在 i18n 的 EN 词典里，或能匹配 RULES 里的带参数模板
  4. 英文词典里不能有中文（没翻完的会在这里露出来）
  5. 带参数的模板：中文与英文的 {} 个数必须一致（漏了会丢参数）
  6. 语言判定：跟随浏览器（zh → 中文，其它 → 英文）
"""
import ast
import re
import sys
from pathlib import Path

CJK = re.compile("[\u4e00-\u9fff]")
LIT = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`')
FAILS = []


def ok(cond, msg):
    print(("  OK  " if cond else "  XX  ") + msg)
    if not cond:
        FAILS.append(msg)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def page_region() -> str:
    text = Path("server.py").read_text(encoding="utf-8")
    m = re.search(r'PAGE = r"""', text)
    start = m.end()
    return text[start:text.index('"""', start)]


def page_js() -> str:
    page = page_region()
    return page[page.index("<script>"):]


def skeleton() -> str:
    page = page_region()
    head = page[: page.index("<script>")]
    return re.sub(r"<style>[\s\S]*?</style>", "", head)      # CSS 注释里的中文不算文案


def literal_end(js: str, i: int) -> int:
    """js[i] 是引号/反引号 → 返回这条字面量结束处的下标（含）。模板里的 ${…} 会递归处理。"""
    q, j, n = js[i], i + 1, len(js)
    while j < n:
        if js[j] == "\\":
            j += 2
            continue
        if js[j] == q:
            return j
        if q == "`" and js[j:j + 2] == "${":          # 模板插值：整段跳过去（里面可能还有字面量）
            depth, k = 1, j + 2
            while k < n and depth:
                if js[k] == "\\":
                    k += 2
                    continue
                if js[k] in "'\"`":
                    k = literal_end(js, k) + 1
                    continue
                if js[k] == "{":
                    depth += 1
                elif js[k] == "}":
                    depth -= 1
                k += 1
            j = k
            continue
        j += 1
    return n - 1


def scan_literals(js: str):
    """逐字符扫出 JS 里的字符串/模板字面量 → [(start, raw)]（跳过注释）。

    为什么不用正则：`T("\\" onclick=\\"go('x')\\">待审提议")` 这种键里混着两种引号，
    正则会把 `'x'` 当成字符串边界而漏掉整条 —— 之前那个「标签混进键」的漏网就是这么漏的。
    """
    out, i, n = [], 0, len(js)
    while i < n:
        c = js[i]
        if c == "/" and i + 1 < n and js[i + 1] == "/":          # 行注释
            nl = js.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        if c == "/" and i + 1 < n and js[i + 1] == "*":          # 块注释
            end = js.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if c in "'\"`":
            end = literal_end(js, i)
            out.append((i, js[i:end + 1]))
            if c == "`":                     # 模板里的 ${…} 是代码，里面还可能有 T('…')，得一并扫出来
                j = i + 1
                while j < end:
                    if js[j] == "\\":
                        j += 2
                        continue
                    if js[j:j + 2] == "${":
                        depth, k = 1, j + 2
                        code_start = k
                        while k < end and depth:
                            if js[k] == "\\":
                                k += 2
                                continue
                            if js[k] in "'\"`":
                                k = literal_end(js, k) + 1
                                continue
                            if js[k] == "{":
                                depth += 1
                            elif js[k] == "}":
                                depth -= 1
                            k += 1
                        for off, raw2 in scan_literals(js[code_start:k - 1]):
                            out.append((code_start + off, raw2))
                        j = k
                        continue
                    j += 1
            i = end + 1
            continue
        i += 1
    return out


def js_string_value(raw: str) -> str:
    """把 JS 字面量的内容解出来（去掉引号与转义）"""
    body = raw[1:-1]
    return (body.replace("\\n", "\n").replace('\\"', '"').replace("\\'", "'")
                .replace("\\`", "`").replace("\\\\", "\\"))


def split_template(body: str):
    """把模板字面量内容切成 [("text", …), ("code", ${…})]，和打包工具同一套规则"""
    parts, buf, i = [], "", 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            buf += body[i:i + 2]
            i += 2
            continue
        if body[i:i + 2] == "${":
            depth, j = 1, i + 2
            while j < len(body) and depth:
                ch = body[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "`":
                    j += 1
                    while j < len(body) and body[j] != "`":
                        j += 2 if body[j] == "\\" else 1
                    j += 1
                    continue
                if ch in "'\"":
                    q, j = ch, j + 1
                    while j < len(body) and body[j] != q:
                        j += 2 if body[j] == "\\" else 1
                    j += 1
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                j += 1
            if buf:
                parts.append(("text", buf))
                buf = ""
            parts.append(("code", body[i:j]))
            i = j
            continue
        buf += c
        i += 1
    if buf:
        parts.append(("text", buf))
    return parts


# 故意保留原样的小字：语言切换按钮上写的是「另一种语言自己的名字」
ALLOW = {"中文", "English", "zh", "en"}


def unwrapped_page_literals():
    """页面 JS 里含中文、却没走 T(…) 的字符串。

    模板字面量：包好之后，模板的**文字段**里不应该再有任何中文（中文都进了 ${T("…")}）。
    """
    js = page_js()
    bad = []
    for start, raw in scan_literals(js):
        body = raw[1:-1]
        if not CJK.search(body) or norm(js_string_value(raw)) in ALLOW:
            continue
        if raw[0] == "`":
            if "${" not in body:                       # 整段模板就是一段中文 → 必须包
                bad.append((js[:start].count("\n") + 1, f"整段模板：{body.strip()[:60]}"))
                continue
            for kind, seg in split_template(body):
                if kind == "text" and CJK.search(seg):
                    bad.append((js[: start].count("\n") + 1, f"模板文字段：{seg.strip()[:60]}"))
        elif not re.search(r"T\(\s*$", js[max(0, start - 36):start]):
            bad.append((js[: start].count("\n") + 1, raw[:70]))
    return bad


def page_keys() -> set:
    """页面里 T("…") 用到的键（用扫出来的字面量，不用正则，免得被混合引号骗过去）"""
    js = page_js()
    keys = set()
    for start, raw in scan_literals(js):
        if raw[0] == "`" or not raw[0] in "'\"":
            continue
        m = re.search(r"(?<![\w$.])T\(\s*$", js[max(0, start - 36):start])
        if not m:
            continue
        rest = js[start + len(raw): start + len(raw) + 4]
        if not re.match(r"\s*[),+}]", rest):          # 后面必须就是右括号/逗号/模板插值的收尾
            continue
        v = norm(js_string_value(raw))
        if CJK.search(v):
            keys.add(v)
    return keys


def backend_literals():
    """后台 Python 里含中文的字符串字面量（文档字符串除外；f-string 把 {} 归一当模板）"""
    out = set()
    for path in ("ops.py", "server.py"):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        docstrings, in_fstring, page_lit = set(), set(), set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                d = ast.get_docstring(node, clean=False)
                if d:
                    docstrings.add(d)
            if isinstance(node, ast.JoinedStr):
                for p in node.values:          # f-string 里的字面量片段不算独立文案
                    in_fstring.add(id(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                v = node.value
                if id(node) in in_fstring or v in docstrings or not CJK.search(v):
                    continue
                if v.lstrip().startswith("<!DOCTYPE html>"):     # 页面整块（页面那边另测）
                    page_lit.add(v)
                    continue
                out.add(norm(v))
            elif isinstance(node, ast.JoinedStr):
                parts = [str(p.value) if isinstance(p, ast.Constant) else "{}" for p in node.values]
                s = norm("".join(parts))
                if CJK.search(s):
                    out.add(s)
    return out


def covered(s: str) -> bool:
    import i18n
    if s in i18n.EN:
        return True
    for k in i18n.RULES:
        parts = k.split("{}")
        if len(parts) < 2:
            continue
        rx = "^" + "(.+?)".join(re.escape(p) for p in parts) + "$"
        if re.match(rx, s, re.S):
            return True
    return False


def main():
    import i18n

    print("1) 页面里有没有漏包的中文")
    miss = unwrapped_page_literals()
    ok(not miss, f"页面 JS 里含中文的字符串都走了 T(…)（漏 {len(miss)} 条）")
    for line, text in miss[:10]:
        print(f"       第 {line} 行：{text}")

    print("\n2) HTML 骨架里的中文（只允许 title/h1/#sub）")
    skel_bad = [l.strip()[:70] for l in skeleton().splitlines()
                if CJK.search(l) and not any(k in l for k in ("<title>", "<h1", 'id="sub"'))]
    ok(not skel_bad, f"骨架里没有别处的中文（{len(skel_bad)} 处）")
    for line in skel_bad[:6]:
        print("       ", line)

    print("\n3) 页面用到的键都有英文")
    pk = page_keys()
    missing_page = sorted(pk - set(i18n.EN))
    ok(not missing_page, f"页面键全部有英文（缺 {len(missing_page)} 条）")
    for k in missing_page[:8]:
        print("       缺：", k[:80])

    print("\n4) 后台每条中文文案都有英文（词典或规则）")
    missing_be = [s for s in sorted(backend_literals()) if not covered(s)]
    ok(not missing_be, f"后台文案全部有英文（缺 {len(missing_be)} 条）")
    for s in missing_be[:12]:
        print("       缺：", s[:90])

    print("\n5) 英文里不能有中文")
    zh_vals = {k: v for k, v in i18n.EN.items() if CJK.search(v or "")}
    ok(not zh_vals, f"英文词典里没有中文（{len(zh_vals)} 条没翻）")
    for k, v in list(zh_vals.items())[:8]:
        print(f"       {k[:40]} → {v[:40]}")

    print("\n6) 带参数模板的 {} 个数要对上")
    bad_rules = [k for k, v in i18n.RULES.items() if k.count("{}") != v.count("{}")]
    ok(not bad_rules, f"中文与英文模板参数个数一致（{len(bad_rules)} 条不对）")
    for k in bad_rules[:6]:
        print("       ", k[:70])

    print("\n7) 语言判定（跟随浏览器）")
    ok(i18n.resolve_lang("zh-CN,zh;q=0.9") == "zh", "zh-CN → 中文")
    ok(i18n.resolve_lang("en-US,en;q=0.9") == "en", "en-US → 英文")
    ok(i18n.resolve_lang("") == "zh", "拿不到头信息 → 中文")
    ok(i18n.resolve_lang("ja-JP") == "en", "其它语言 → 英文")

    print()
    if FAILS:
        print(f"XX 双语验收没通过：{len(FAILS)} 项")
        return 1
    print("OK 双语验收全部通过：没有漏翻的中文、英文里没有中文残留")
    return 0


if __name__ == "__main__":
    sys.exit(main())
