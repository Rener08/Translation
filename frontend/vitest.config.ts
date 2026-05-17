import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["./setupTests.ts"],
    restoreMocks: true,
    clearMocks: true,
    mockReset: true,
  },
});
