import { defineConfig } from "vite";

export default defineConfig({
  test: {
    include: ["src/**/*.test.js"],
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
