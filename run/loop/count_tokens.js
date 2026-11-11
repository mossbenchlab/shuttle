const fs = require("fs");
const { encode } = require("gpt-tokenizer/encoding/o200k_base");
const dir = __dirname;
const out = {};
let tot = {solver: 0, receipt: 0};
for (const t of ["L1","L2","L3","L4","L5","L6"]) {
  const s = JSON.parse(fs.readFileSync(`${dir}/${t}.state.json`, "utf8"));
  const so = s.messages.reduce((a, m) => a + encode(m).length, 0);
  const re = s.receipts.reduce((a, m) => a + encode(m).length, 0);
  const prompt = encode(fs.readFileSync(`${dir}/${t}.prompt.md`, "utf8")).length;
  out[t] = {solver_output_tokens: so, receipt_tokens: re, prompt_tokens: prompt, messages: s.messages.length};
  tot.solver += so; tot.receipt += re;
}
out.total = tot;
if (process.argv[3]) out.data_json_tokens = encode(fs.readFileSync(process.argv[3], "utf8")).length;
fs.writeFileSync(`${dir}/tokens.json`, JSON.stringify(out, null, 1));
console.log(JSON.stringify(out, null, 1));
