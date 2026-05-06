import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const isProd = mode === "production";
  return {
    plugins: [react()],
    server: {
      port: 5173,
    },
    esbuild: {
      drop: isProd ? ["console", "debugger"] : [],
      legalComments: "none",
    },
    build: {
      sourcemap: false,
      minify: "esbuild",
      cssMinify: true,
      rollupOptions: {
        output: isProd
          ? {
              entryFileNames: "assets/[hash].js",
              chunkFileNames: "assets/[hash].js",
              assetFileNames: "assets/[hash][extname]",
            }
          : {},
      },
    },
  };
});
