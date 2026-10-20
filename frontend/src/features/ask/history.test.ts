/** The conversation store: per study, ordered, capped, and recall without repeats. */
import { afterEach, describe, expect, it } from "vitest";
import {
  addTurn,
  clearTurns,
  getTurns,
  MAX_TURNS,
  recallList,
  resetAllTurns,
  updateTurn,
} from "./history";

afterEach(resetAllTurns);

describe("history", () => {
  it("keeps one conversation per study", () => {
    addTurn("study-a", "Is the result robust?");
    addTurn("study-b", "What should I check first?");
    expect(getTurns("study-a").map((t) => t.question)).toEqual(["Is the result robust?"]);
    expect(getTurns("study-b").map((t) => t.question)).toEqual(["What should I check first?"]);
    clearTurns("study-a");
    expect(getTurns("study-a")).toEqual([]);
    expect(getTurns("study-b")).toHaveLength(1);
  });

  it("updates one turn in place", () => {
    const t = addTurn("s", "first");
    addTurn("s", "second");
    updateTurn("s", t.id, { state: "running", jobId: "job-x" });
    const [first, second] = getTurns("s");
    expect(first).toMatchObject({ question: "first", state: "running", jobId: "job-x" });
    expect(second).toMatchObject({ question: "second", state: "sending", jobId: null });
  });

  it(`drops the oldest beyond ${MAX_TURNS} turns`, () => {
    for (let i = 0; i <= MAX_TURNS; i += 1) addTurn("s", `question ${i}`);
    const turns = getTurns("s");
    expect(turns).toHaveLength(MAX_TURNS);
    expect(turns[0]!.question).toBe("question 1");
  });

  it("recalls the most recent question first, each once", () => {
    for (const q of ["a", "b", "a", "c"]) addTurn("s", q);
    expect(recallList(getTurns("s"))).toEqual(["c", "a", "b"]);
  });
});
