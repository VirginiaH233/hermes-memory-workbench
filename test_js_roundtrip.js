// test_js_roundtrip.js —— 用**页面里真正在跑的那段代码**验证排版不会改字。
//
// 做法：从 server.py 里把 //--transform-start-- ... //--transform-end-- 之间的
// 代码原样抓出来执行（不是抄一份，抄的会漂移），然后拿 /api/state 的全部真实文字
// 做「排版 → 折回」往返，要求逐字节相等。
//
// 为什么必须这么测：只要这两段不严格互逆，你「打开页面、什么都没改、点保存」
// 就会悄悄改动记忆文字。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(here, 'server.py'), 'utf8');
const m = src.match(/\/\/--transform-start--[\s\S]*?\/\/--transform-end--/);
if (!m) { console.error('❌ 没找到 transform 标记'); process.exit(1); }
const code = m[0].replace(/\/\/--transform-(start|end)--.*$/gm, '');
const { pretty, collapse } = new Function(`${code}; return {pretty, collapse};`)();

const state = await (await fetch('http://127.0.0.1:8787/api/state')).json();
const texts = [];
for (const t of ['memory', 'user']) for (const e of state.memory[t]) texts.push(['记忆:' + t, e]);
for (const r of state.records) r.ops.forEach((o, i) => texts.push(['提议:' + r.id + '#' + (i + 1), o.content]));

const bad = [];
for (const [label, x] of texts) {
  const y = collapse(pretty(x));
  if (y !== x) bad.push([label, x, y]);
}

console.log(`检查了 ${texts.length} 段真实文字`);
if (!bad.length) {
  console.log('✅ 往返无损：打开 → 不改 → 保存，记忆逐字节不变');
  process.exit(0);
}
console.log(`❌ 有 ${bad.length} 段会被改动：\n`);
for (const [label, x, y] of bad.slice(5)) {
  console.log(`--- ${label}\n原：${JSON.stringify(x.slice(0, 200))}\n后：${JSON.stringify(y.slice(0, 200))}\n`);
}
process.exit(1);
