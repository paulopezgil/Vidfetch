import { readdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const PRECACHE_MANIFEST = "precache-manifest.json";

/**
 * Write the full build file list for the service worker to precache.
 *
 * The app shell is useless offline unless every hashed JS/CSS chunk it can ask
 * for is present, including lazy route chunks. The service worker cannot know
 * those names at build time, so the build leaves a manifest next to them.
 */
function precacheManifest(): Plugin {
  let outDir = "";

  return {
    name: "vidfetch-precache-manifest",
    apply: "build",
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir);
    },
    closeBundle() {
      if (!outDir) return;

      const files: string[] = [];
      const walk = (dir: string, prefix: string) => {
        for (const entry of readdirSync(dir, { withFileTypes: true })) {
          const relative = `${prefix}/${entry.name}`;
          if (entry.isDirectory()) walk(join(dir, entry.name), relative);
          else files.push(relative);
        }
      };
      walk(outDir, "");

      const entries = files
        .filter(
          (file) =>
            file !== "/sw.js" && file !== `/${PRECACHE_MANIFEST}`,
        )
        .sort();
      writeFileSync(
        join(outDir, PRECACHE_MANIFEST),
        `${JSON.stringify(entries, null, 2)}\n`,
      );
    },
  };
}

export default defineConfig({
  plugins: [react(), precacheManifest()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
