import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// base: "./" → 번들 자산 URL 이 전부 상대경로가 된다.
// HEAXHub Caddy 가 /apps/voice_recorder/ 서브경로로 마운트해도 자산이 깨지지 않는다.
export default defineConfig({
    plugins: [react()],
    base: "./",
    build: {
        outDir: "dist",
        emptyOutDir: true,
    },
    server: {
        port: 5273,
        // 개발 중에만 쓰는 프록시. 배포 시에는 FastAPI 가 같은 origin 에서 /api 를 서빙한다.
        proxy: {
            "/api": {
                target: "http://127.0.0.1:8000",
                changeOrigin: true,
            },
        },
    },
});
