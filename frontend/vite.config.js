import { defineConfig } from 'vite';
import path from 'path';

export default defineConfig({
  root: path.resolve(__dirname, 'js'),
  base: '/static/dist/',
  build: {
    outDir: path.resolve(__dirname, '../app/static/dist'),
    emptyOutDir: true,
    assetsDir: '',
    sourcemap: true, // Enable for debugging, remove for prod if not needed
    minify: 'esbuild', // Ensure minification
    rollupOptions: {
      output: {
        entryFileNames: 'app.js',
        chunkFileNames: 'chunks/[name]-[hash].js',
        assetFileNames: '[name][extname]',
        manualChunks(id) {
          if (id.includes('node_modules')) return 'vendor';
          if (id.includes('controllers')) return 'controllers';
        }
      },
      input: {
        main: path.resolve(__dirname, 'js/app.js')
      }
    }
  }
});
