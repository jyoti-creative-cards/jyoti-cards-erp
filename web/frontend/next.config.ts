import type { NextConfig } from "next";

/**
 * Browser → same-origin `/erp-api/*` → FastAPI (fixes CORS + SSR fetch to backend).
 * Set `API_PROXY_TARGET` for deploy (Railway URL); local default 127.0.0.1:8000.
 */
const API_ORIGIN = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/erp-api/:path*",
        destination: `${API_ORIGIN.replace(/\/$/, "")}/:path*`,
      },
    ];
  },
};

export default nextConfig;
