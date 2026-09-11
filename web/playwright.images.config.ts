// Focused owned image worlds; also included in the full packaged configuration.
import { defineConfig } from "@playwright/test";
import packaged from "./playwright.config";
const { globalSetup: _setup, globalTeardown: _teardown, ...base } = packaged;
export default defineConfig({ ...base, testMatch: "image-identity.spec.ts" });
