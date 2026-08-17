// @ts-expect-error Vite runs in Node; this project intentionally omits @types/node.
import { execFileSync } from "node:child_process";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

function gitValue(args: string[], fallback: string) {
  try {
    return execFileSync("git", args, { encoding: "utf8" }).trim() || fallback;
  } catch {
    return fallback;
  }
}

const buildSha = gitValue(["rev-parse", "--short=12", "HEAD"], "unknown");
const buildTime = new Date().toISOString();

// 本地控制台：仅 127.0.0.1；/api 代理到 FastAPI（010 四十六）
export default defineConfig({
  define: {
    __APP_BUILD_SHA__: JSON.stringify(buildSha),
    __APP_BUILD_TIME__: JSON.stringify(buildTime),
  },
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
  },
});
