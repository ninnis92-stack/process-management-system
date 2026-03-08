import { defineConfig } from 'vite';
import path from 'path';

export default defineConfig({
  root: path.resolve(__dirname, 'js'),
  base: '/static/dist/',
  build: {
    outDir: path.resolve(__dirname, '../app/static/dist'),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, 'js/app.js')
      }
    }
  }
});
