import { describe, expect, it } from "vitest";
import { canonicalBody, canonicalJson, demoKey, isRead, keySource } from "./key";

const url = (s: string) => new URL(s, "http://127.0.0.1");

describe("the online demo's keys", () => {
  it("sorts the query, so the order a page writes it in does not matter", () => {
    expect(keySource("get", url("/api/x?b=2&a=1&a=0"))).toBe("GET /api/x?a=0&a=1&b=2");
    expect(keySource("GET", url("/api/x"))).toBe("GET /api/x");
  });

  it("reads a POST body as canonical JSON (sorted keys, no spacing)", () => {
    expect(canonicalJson({ b: [2, { d: 1, c: null }], a: "x", u: undefined })).toBe(
      '{"a":"x","b":[2,{"c":null,"d":1}]}',
    );
    expect(canonicalBody('{ "z": 1, "a": {"y": true, "b": 2} }')).toBe(
      '{"a":{"b":2,"y":true},"z":1}',
    );
    expect(canonicalBody("not json")).toBe("not json");
    expect(canonicalBody(null)).toBe("");
    expect(keySource("POST", url("/api/s/1/claims"), '{"text":"a"}')).toBe(
      'POST /api/s/1/claims\n{"text":"a"}',
    );
  });

  it("gives equal requests equal keys and different requests different ones", async () => {
    const a = await demoKey("POST", url("/api/p?x=1"), '{"a":1,"b":2}');
    const b = await demoKey("POST", url("/api/p?x=1"), '{"b":2,"a":1}');
    const c = await demoKey("POST", url("/api/p?x=1"), '{"a":1,"b":3}');
    expect(a).toMatch(/^[0-9a-f]{32}$/);
    expect(b).toBe(a);
    expect(c).not.toBe(a);
    expect(await demoKey("GET", url("/api/p?x=1"))).not.toBe(await demoKey("GET", url("/api/p")));
  });

  it("answers only reads: GETs and the POSTs that compute without writing", () => {
    expect(isRead("GET", "/api/studies/abc/results")).toBe(true);
    expect(isRead("POST", "/api/studies/abc/audit/whatif")).toBe(true);
    expect(isRead("POST", "/api/studies/abc/claims")).toBe(true);
    expect(isRead("POST", "/api/studies/abc/planner/layout")).toBe(true);
    expect(isRead("POST", "/api/studies/abc/trace/ODC1/without")).toBe(true);
    expect(isRead("POST", "/api/studies/abc/cards/c1/decide")).toBe(false);
    expect(isRead("POST", "/api/sessions/s/proposals/p/accept")).toBe(false);
    expect(isRead("POST", "/api/workspaces")).toBe(false);
    expect(isRead("PUT", "/api/settings")).toBe(false);
    expect(isRead("POST", "/api/studies/abc/claims/read")).toBe(false);
  });
});
