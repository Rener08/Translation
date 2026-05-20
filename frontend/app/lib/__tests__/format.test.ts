import { describe, expect, it } from "vitest";

import { normalizeApiErrorMessage } from "../format";

describe("normalizeApiErrorMessage", () => {
  it("renders PO Token guidance", () => {
    expect(
      normalizeApiErrorMessage(
        "ERROR: [youtube] 403 Forbidden: this client requires a PO Token",
        "PO_TOKEN_REQUIRED",
      ),
    ).toContain("PO Token");
  });

  it("falls back to PO Token guidance from raw text", () => {
    expect(
      normalizeApiErrorMessage(
        "ERROR: [youtube] [pot] PO Token Providers: none",
      ),
    ).toContain("PO Token");
  });
});
