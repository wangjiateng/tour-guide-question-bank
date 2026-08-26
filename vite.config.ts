import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  // 纯静态部署：相对 base，可放到任意子路径（hash 路由，无需服务端回退）
  base: "./",
  build: { outDir: "dist", emptyOutDir: true },
});
