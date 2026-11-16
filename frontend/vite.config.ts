import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/nexusportal/",
  server: { proxy: { "/nexusportal/api": { target: "http://127.0.0.1:8787", rewrite: (path) => path.replace(/^\\/nexusportal/, "") } } },
  build: { target: "es2020", sourcemap: false },
});
