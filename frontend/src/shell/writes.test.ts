import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/client";

const toast = vi.hoisted(() => ({ error: vi.fn(), info: vi.fn(), warning: vi.fn() }));
vi.mock("@/ui", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/ui")>()),
  toast,
}));

import { reportWriteError } from "./writes";

afterEach(() => vi.clearAllMocks());

describe("a write the shared sandbox will not take now", () => {
  const words = "This shared sandbox is busy for you: try again in 20 seconds.";

  it("is said in the server's words, for about as long as it asks to wait", () => {
    const busy = new ApiError(429, "rate_limited", words, { retry_after_s: 20 });
    reportWriteError(new QueryClient(), busy);
    expect(toast.warning).toHaveBeenCalledWith("The shared sandbox is busy", {
      description: words,
      duration: 20_000,
    });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("stays at least a few seconds, and never until it is closed", () => {
    reportWriteError(
      new QueryClient(),
      new ApiError(429, "rate_limited", words, { retry_after_s: 1 }),
    );
    reportWriteError(
      new QueryClient(),
      new ApiError(429, "rate_limited", words, { retry_after_s: 600 }),
    );
    reportWriteError(new QueryClient(), new ApiError(429, "rate_limited", words));
    expect(toast.warning.mock.calls.map((c) => c[1].duration)).toEqual([8_000, 30_000, 8_000]);
  });

  it("is not how any other refusal is shown", () => {
    reportWriteError(new QueryClient(), new ApiError(409, "studio", "Confirm the design first."));
    expect(toast.error).toHaveBeenCalledWith("Not yet", {
      description: "Confirm the design first.",
      duration: Infinity,
    });
    expect(toast.warning).not.toHaveBeenCalled();
  });
});
