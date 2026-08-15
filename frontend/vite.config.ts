import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      {
        find: "~@ibm/plex",
        replacement: fileURLToPath(new URL("./node_modules/@ibm/plex", import.meta.url))
      }
    ]
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/ready": "http://127.0.0.1:8000",
      "/metrics": "http://127.0.0.1:8000",
      "/ws": {
        target: "ws://127.0.0.1:8000",
        ws: true
      }
    }
  },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: "echarts-runtime",
              test: /node_modules[\\/](echarts|zrender)[\\/]/,
              minSize: 100_000,
              maxSize: 300_000,
              priority: 20
            }
          ]
        }
      }
    }
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test-setup.ts"],
    css: true,
    server: {
      deps: {
        inline: ["jsdom", "parse5", "@exodus/bytes", "whatwg-url", "html-encoding-sniffer"]
      }
    }
  }
});
