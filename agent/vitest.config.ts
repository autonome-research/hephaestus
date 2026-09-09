import { defineConfig } from "vitest/config";

// Source modules use NodeNext ".js" specifiers that resolve to ".ts" on disk.
// Vite resolves these for the browser/build graph; this plugin makes the same
// rewrite for Vitest's Node test graph so tests can import the real source.
export default defineConfig({
  plugins: [
    {
      name: "resolve-js-to-ts",
      enforce: "pre",
      async resolveId(source, importer) {
        if (importer && source.startsWith(".") && source.endsWith(".js")) {
          const resolved = await this.resolve(
            source.slice(0, -3) + ".ts",
            importer,
            { skipSelf: true },
          );
          if (resolved) return resolved;
        }
        return null;
      },
    },
  ],
  test: {
    include: ["test/**/*.test.ts"],
    environment: "node",
    // Runs before any test module is imported, which is what makes it able to
    // set `HEPHAESTUS_AGENT_DIR`: `src/main.ts` reads it at module load and
    // otherwise falls back to `process.cwd()` — this package's own directory.
    setupFiles: ["./test/setup.ts"],
  },
});
