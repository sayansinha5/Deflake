import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const securityHeaders = {
  "Content-Security-Policy":
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; " +
    "font-src 'self'; img-src 'self' data:; connect-src 'self' http://localhost:8000; " +
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
  "X-Frame-Options": "DENY",
};

const refreshPreamble = `import { injectIntoGlobalHook } from "/@react-refresh";
injectIntoGlobalHook(window);
window.$RefreshReg$ = () => {};
window.$RefreshSig$ = () => (type) => type;
`;

function externalRefreshPreamble() {
  return {
    name: "external-refresh-preamble",
    transformIndexHtml: {
      order: "post",
      handler(html) {
        return html.replace(
          /<script type="module">import \{ injectIntoGlobalHook \}[\s\S]*?<\/script>/,
          '<script type="module" src="/refresh-preamble.js"></script>',
        );
      },
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.split("?")[0] !== "/refresh-preamble.js") {
          next();
          return;
        }
        res.setHeader("Content-Type", "text/javascript");
        res.end(refreshPreamble);
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), externalRefreshPreamble()],
  server: {
    host: process.env.VITE_BIND_HOST || "127.0.0.1",
    port: 5173,
    strictPort: true,
    headers: securityHeaders,
  },
  preview: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    headers: securityHeaders,
  },
});
