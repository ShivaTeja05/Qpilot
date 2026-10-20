import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
// Recorded with the real core.record.verify: see recorded/record_verify.py.
import ok from "./recorded/verify-ok.json";
import tampered from "./recorded/verify-tampered.json";
import { renderWithProviders } from "./test-utils";
import type { VerifyResult } from "./types";
import { VerifyReportView, verifyRows } from "./VerifyCard";

afterEach(cleanup);

describe("verify report", () => {
  it("passes every check of an untouched record", () => {
    const rows = verifyRows(ok as VerifyResult);
    expect(rows.map((r) => r.state)).toEqual(["pass", "pass", "pass", "pass"]);
    renderWithProviders(<VerifyReportView report={ok as VerifyResult} fileName="record.zip" />);
    expect(screen.getByText("This record checks out")).toBeTruthy();
    expect(screen.getByText(new RegExp(`${(ok as VerifyResult).n_entries} entries, every hash links`))).toBeTruthy();
  });

  it("names what changed in a tampered record", () => {
    const report = tampered as VerifyResult;
    const rows = verifyRows(report);
    expect(rows.find((r) => r.title === "Checksums")?.state).toBe("fail");
    expect(rows.find((r) => r.title === "Decision chain")?.state).toBe("fail");
    renderWithProviders(<VerifyReportView report={report} />);
    expect(screen.getByText("This record was changed after it was exported")).toBeTruthy();
    expect(screen.getByText(/Changed since export: decisions.jsonl/)).toBeTruthy();
    expect(screen.getByText(new RegExp(`Broken at entry ${report.chain_broken_at}`))).toBeTruthy();
  });
});
