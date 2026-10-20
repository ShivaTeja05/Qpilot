import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ExportCard } from "./ExportCard";
// Recorded from GET /api/studies/{id}/records after exporting on the Record page: see recorded/README.md.
import recorded from "./recorded/records-e300000d4f9a.json";
import { renderWithProviders } from "./test-utils";
import type { RecordList } from "./types";

const { records } = recorded as unknown as RecordList;
const latest = records[0]!;

afterEach(cleanup);

function show(head: string | null, disabledReason?: string) {
  renderWithProviders(
    <ExportCard
      workspaceKey="bc1d233e3866"
      studyId={latest.study_id}
      head={head}
      jobId={null}
      onJob={() => {}}
      records={records}
      disabledReason={disabledReason}
    />,
  );
}

describe("ExportCard", () => {
  it("shows the latest record in full: download, files, the server's warnings, where it is kept", () => {
    show(latest.chain_head);
    const link = screen.getByRole("link", { name: new RegExp(`Download ${latest.download.name}`) });
    expect(link.getAttribute("href")).toBe(latest.download.url);
    expect(link.getAttribute("download")).toBe(latest.download.name);
    expect(screen.getByText("same as the timeline")).toBeTruthy();
    for (const w of latest.warnings) expect(screen.getByText(w)).toBeTruthy();
    expect(screen.getByText(latest.download.path)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Export again" })).toBeTruthy();
  });

  it("lists earlier exports with their own downloads", () => {
    show(latest.chain_head);
    expect(screen.getByText("Exported earlier since qPilot started")).toBeTruthy();
    expect(screen.getAllByRole("link", { name: /^Download/ })).toHaveLength(records.length);
  });

  it("says when decisions were made after the latest record", () => {
    show(`${latest.chain_head.slice(0, -1)}${latest.chain_head.endsWith("0") ? "1" : "0"}`);
    expect(screen.getByText(/Decisions were made after this record was exported/)).toBeTruthy();
  });

  it("cannot export before the study is analysed, and says why", () => {
    show(null, "The record starts when this study is analysed: confirm the design and the curves first.");
    expect((screen.getByRole("button", { name: "Export again" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/confirm the design and the curves first/)).toBeTruthy();
  });
});
