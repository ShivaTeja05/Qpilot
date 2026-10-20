import { describe, expect, it } from "vitest";
// Recorded with the real core.record.verify: see recorded/record_verify.py.
import ok from "./recorded/verify-ok.json";
import tampered from "./recorded/verify-tampered.json";
import type { VerifyReport } from "./types";
import { verifyRows } from "./VerifyCard";

describe("verify report rows", () => {
  it("passes every check of an untouched record", () => {
    const rows = verifyRows(ok as VerifyReport);
    expect(rows.map((r) => r.state)).toEqual(["pass", "pass", "pass", "pass"]);
    expect(rows[1]!.detail).toMatch(new RegExp(`${(ok as VerifyReport).n_entries} entries, every hash links`));
  });

  it("names what changed in a tampered record", () => {
    const report = tampered as VerifyReport;
    const rows = verifyRows(report);
    expect(rows.find((r) => r.title === "Checksums")?.state).toBe("fail");
    const chain = rows.find((r) => r.title === "Decision chain");
    expect(chain?.state).toBe("fail");
    expect(chain?.detail).toMatch(new RegExp(`Broken at entry ${report.chain_broken_at}`));
  });
});
