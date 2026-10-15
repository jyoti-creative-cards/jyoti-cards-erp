import type { NextConfig } from "next";

/** Same machine as customer-app dev (3000) → avoids localhost vs 127.0.0.1 CORS issues. */
const backend = (
  process.env.BACKEND_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8002"
).replace(/\/$/, "");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/proxy/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
