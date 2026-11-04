import { describe, expect, it } from "vitest";

import { selectVisibleStems } from "./AgentStemStack";

describe("AgentStemStack visible lanes", () => {
  it("renders only stems reported complete, in the canonical track order", () => {
    expect(selectVisibleStems(["vocals", "drums"]).map(({ name }) => name)).toEqual([
      "vocals",
      "drums",
    ]);
  });

  it("keeps the legacy full-stack view when no availability list is provided", () => {
    expect(selectVisibleStems().map(({ name }) => name)).toEqual([
      "vocals",
      "drums",
      "bass",
      "other",
    ]);
  });
});
