import { defineConfig } from 'vite';

// GitHub Pages のサブパス配信でも動くよう相対パスにする
export default defineConfig({
  base: './',
});
