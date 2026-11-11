const fs = require("fs"); const { encode } = require("gpt-tokenizer/encoding/o200k_base");
function load(dir, t) { const s = JSON.parse(fs.readFileSync(`${dir}/${t}.state.json`, "utf8")); return s.log ? s.log.filter(e => e.who === "solver").map(e => [e.message, e.receipt]) : s.messages.map((m, i) => [m, s.receipts[i]]); }
const out = {};
for (const [dir, t] of [["loop","L1.h"],["loop","L2.h"],["loop","L3.h"],["loop","L4.h"],["loop","L5.h"],["loop","L6.h2"],["loop2","M1.h"],["loop2","M2.h"],["loop2","M3.h"],["loop2","M4.h"],["loop2","M5.h"],["loop2","M6.h"]]) {
  const log = load(`${__dirname}/${dir}`, t);
  out[t] = {messages: log.length, solver: log.reduce((a, e) => a + encode(e[0]).length, 0), receipt: log.reduce((a, e) => a + encode(e[1]).length, 0), fails: log.filter(e => e[1].startsWith("fail")).length};
}
fs.writeFileSync(__dirname + "/tokens_haiku.json", JSON.stringify(out, null, 1)); console.log(JSON.stringify(out));
