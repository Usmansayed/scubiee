import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  base: '/', // <-- change this line

  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          wasm: ['@ffmpeg/ffmpeg'],
        },
      },
    },
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
        drop_debugger: true,
      },
    },
  },

  optimizeDeps: {
    exclude: ['@ffmpeg/ffmpeg', '@ffmpeg/util'],
  },

  plugins: [
    VitePWA({
      registerType: 'autoUpdate',
      manifest: require('./public/manifest.json'), // If it's stored in /public
      workbox: {
        runtimeCaching: [
          {
            urlPattern: ({ request }) => request.destination === 'document',
            handler: 'NetworkFirst',
          },
          {
            urlPattern: ({ request }) => request.destination === 'image',
            handler: 'CacheFirst',
          },
          {
            urlPattern: ({ request }) => request.destination === 'script' || request.destination === 'style',
            handler: 'StaleWhileRevalidate',
          },
        ],
      },
      devOptions: {
        enabled: true
      }
    })
  ]
});
