import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
// Recorded from POST /api/records/verify on a real export, untouched, with one decision line
// edited, and with one byte of its zip flipped: see recorded/README.md.
import flippedJson from "./recorded/verified-flipped.json";
import ok from "./recorded/verified-ok.json";
import tampered from "./recorded/verified-tampered.json";
import { CommandsCard } from "./CommandsCard";
import { renderWithProviders } from "./test-utils";
import type { VerifyResult } from "./types";
import { VerifyResultView, verifyRows } from "./VerifyCard";

const good = ok as unknown as VerifyResult;
const bad = tampered as unknown as VerifyResult;
const flipped = flippedJson as unknown as VerifyResult;

afterEach(cleanup);

describe("verify a record", () => {
  it("passes every check of an untouched record, the audit included", () => {
    const rows = verifyRows(good.report, good);
    expect(rows.map((r) => r.state)).toEqual([
      "pass",
      "pass",
      "pass",
      "pass",
      good.audit ? "pass" : "absent",
    ]);
    renderWithProviders(<VerifyResultView result={good} />);
    expect(screen.getByText("This record checks out")).toBeTruthy();
    expect(
      screen.getByText(new RegExp(`${good.report.n_entries} entr(y|ies), every hash links`)),
    ).toBeTruthy();
    expect(screen.getByText(good.audit_note)).toBeTruthy();
    expect(screen.getByText(good.note)).toBeTruthy();
  });

  it("names what changed in a tampered record", () => {
    const rows = verifyRows(bad.report, bad);
    expect(rows.find((r) => r.title === "Checksums")?.state).toBe("fail");
    expect(rows.find((r) => r.title === "Decision chain")?.state).toBe("fail");
    renderWithProviders(<VerifyResultView result={bad} />);
    expect(screen.getByText("This record was altered or damaged after export")).toBeTruthy();
    expect(screen.getByText(new RegExp(bad.headline.replace(".", "\\.")))).toBeTruthy();
    for (const name of bad.report.changed)
      expect(screen.getByText(new RegExp(`Changed since export: ${name}`))).toBeTruthy();
    expect(
      screen.getByText(new RegExp(`Broken at entry ${bad.report.chain_broken_at}`)),
    ).toBeTruthy();
  });

  it("calls a zip with one flipped byte altered, naming the file, not 'could not be checked'", () => {
    expect(flipped.outcome).toBe("altered");
    expect(flipped.report.damaged).toEqual(["decisions.jsonl"]);
    const rows = verifyRows(flipped.report, flipped);
    expect(rows.find((r) => r.title === "Checksums")?.state).toBe("fail");
    renderWithProviders(<VerifyResultView result={flipped} />);
    expect(screen.getByText("This record was altered or damaged after export")).toBeTruthy();
    expect(
      screen.getByText(/This record was altered or damaged after export: decisions\.jsonl\./),
    ).toBeTruthy();
    expect(screen.getByText(/fail the zip’s own check\): decisions\.jsonl/)).toBeTruthy();
    expect(screen.getByText(/Not readable: the decision log/)).toBeTruthy();
  });

  it("names the dropped file in the terminal commands", () => {
    renderWithProviders(<CommandsCard commands={null} dropped="flipped record.zip" />);
    expect(screen.getByText("qpilot verify 'flipped record.zip'")).toBeTruthy();
    expect(screen.getByText("qpilot rerun 'flipped record.zip'")).toBeTruthy();
    cleanup();
    renderWithProviders(<CommandsCard commands={null} dropped="rec-2.zip" />);
    expect(screen.getByText("qpilot verify rec-2.zip")).toBeTruthy();
  });

  it("says what the record says about itself", () => {
    renderWithProviders(<VerifyResultView result={good} />);
    expect(screen.getByText(good.record.study_id!)).toBeTruthy();
    expect(
      screen.getByText(good.known_study ? /yes, this study is in this qPilot/ : /^no$/),
    ).toBeTruthy();
  });
});
