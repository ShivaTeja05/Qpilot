import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
// Recorded from POST /api/records/verify on a real export, untouched and with one decision line
// edited: see recorded/README.md.
import ok from "./recorded/verified-ok.json";
import tampered from "./recorded/verified-tampered.json";
import { renderWithProviders } from "./test-utils";
import type { VerifyResult } from "./types";
import { VerifyResultView, verifyRows } from "./VerifyCard";

const good = ok as unknown as VerifyResult;
const bad = tampered as unknown as VerifyResult;

afterEach(cleanup);

describe("verify a record", () => {
  it("passes every check of an untouched record, the audit included", () => {
    const rows = verifyRows(good.report, good);
    expect(rows.map((r) => r.state)).toEqual(["pass", "pass", "pass", "pass", good.audit ? "pass" : "absent"]);
    renderWithProviders(<VerifyResultView result={good} />);
    expect(screen.getByText("This record checks out")).toBeTruthy();
    expect(screen.getByText(new RegExp(`${good.report.n_entries} entries, every hash links`))).toBeTruthy();
    expect(screen.getByText(good.audit_note)).toBeTruthy();
    expect(screen.getByText(good.note)).toBeTruthy();
  });

  it("names what changed in a tampered record", () => {
    const rows = verifyRows(bad.report, bad);
    expect(rows.find((r) => r.title === "Checksums")?.state).toBe("fail");
    expect(rows.find((r) => r.title === "Decision chain")?.state).toBe("fail");
    renderWithProviders(<VerifyResultView result={bad} />);
    expect(screen.getByText("This record does not check out")).toBeTruthy();
    for (const name of bad.report.changed) expect(screen.getByText(new RegExp(`Changed since export: ${name}`))).toBeTruthy();
    expect(screen.getByText(new RegExp(`Broken at entry ${bad.report.chain_broken_at}`))).toBeTruthy();
  });

  it("says what the record says about itself", () => {
    renderWithProviders(<VerifyResultView result={good} />);
    expect(screen.getByText(good.record.study_id!)).toBeTruthy();
    expect(screen.getByText(good.known_study ? /yes, this study is in this qPilot/ : /^no$/)).toBeTruthy();
  });
});
