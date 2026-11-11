const fs = require("fs"); const { encode } = require("gpt-tokenizer/encoding/o200k_base");
const dir = __dirname; const out = {}; let tot = {solver: 0, receipt: 0};
for (const t of ["M1","M2","M3","M4","M5","M6","M2b","M3b","M4b"]) {
  const s = JSON.parse(fs.readFileSync(`${dir}/${t}.state.json`, "utf8")).log.filter(e => e.who === "solver");
  const so = s.reduce((a, e) => a + encode(e.message).length, 0), re = s.reduce((a, e) => a + encode(e.receipt).length, 0);
  out[t] = {solver_output_tokens: so, receipt_tokens: re, prompt_tokens: encode(fs.readFileSync(`${dir}/${t}.prompt.md`, "utf8")).length, messages: s.length};
  tot.solver += so; tot.receipt += re;
}
out.total = tot; fs.writeFileSync(`${dir}/tokens.json`, JSON.stringify(out, null, 1)); console.log(JSON.stringify(out));
