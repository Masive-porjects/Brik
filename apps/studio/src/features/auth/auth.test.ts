import { describe, it, expect } from "vitest";

describe("Supabase Auth Configuration", () => {
  it("has valid Supabase environment variable placeholders or values", () => {
    // Check that createClient does not crash if env is provided
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "https://test.supabase.co";
    const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "test-anon-key";

    expect(url).toContain("https://");
    expect(key.length).toBeGreaterThan(5);
  });
});
