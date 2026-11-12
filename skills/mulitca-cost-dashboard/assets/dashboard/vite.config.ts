import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  root: 'web',
  plugins: [react()],
  build: { outDir: '../web-dist', emptyOutDir: true },
  test: { include: ['test/**/*.test.ts'] },
});
