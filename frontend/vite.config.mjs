import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  root: ".",          // tells Vite to look in the current folder for index.html
  publicDir: "public" // optional, where static files live
});