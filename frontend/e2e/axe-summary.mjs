#!/usr/bin/env node
// Group the axe findings saved by the e2e run (e2e/screenshots/axe/*.json) by rule and element,
// with the page states each one was seen in, as Markdown for the owners.
//
//   node e2e/axe-summary.mjs [DIR] [--all]     (default: serious and critical only)
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const args = process.argv.slice(2);
const all = args.includes("--all");
const dir = args.find((a) => !a.startsWith("--")) ?? "e2e/screenshots/axe";
const failing = new Set(["serious", "critical"]);

const groups = new Map();
for (const file of readdirSync(dir).filter((f) => f.endsWith(".json"))) {
  const { state, findings } = JSON.parse(readFileSync(join(dir, file), "utf8"));
  for (const f of findings) {
    if (!all && !failing.has(f.impact)) continue;
    for (const n of f.nodes) {
      // Same element, same reason: one line (colours and ratio are part of the reason).
      const key = `${f.id}\u0000${n.html}\u0000${n.why}`;
      const g = groups.get(key) ?? {
        rule: f.id,
        impact: f.impact,
        help: f.help,
        ...n,
        states: new Set(),
      };
      g.states.add(state);
      groups.set(key, g);
    }
  }
}

const byRule = new Map();
for (const g of groups.values()) {
  const list = byRule.get(g.rule) ?? [];
  list.push(g);
  byRule.set(g.rule, list);
}

const lines = [`# axe findings (${all ? "all impacts" : "serious and critical"}) from ${dir}`, ""];
for (const [rule, list] of [...byRule].sort((a, b) => b[1].length - a[1].length)) {
  lines.push(`## ${rule} (${list[0].impact}): ${list[0].help} — ${list.length} element(s)`, "");
  for (const g of list.sort((a, b) => b.states.size - a.states.size)) {
    const states = [...g.states].sort();
    lines.push(`- \`${g.html.replace(/\s+/g, " ").slice(0, 160)}\``);
    lines.push(`  - ${g.why.slice(0, 260)}`);
    lines.push(
      `  - seen in ${states.length}: ${states.slice(0, 6).join("; ")}${states.length > 6 ? "; …" : ""}`,
    );
  }
  lines.push("");
}
console.log(lines.join("\n"));
