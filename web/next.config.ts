import type { NextConfig } from "next";

// The FastAPI server (datadraft serve). /api/* is proxied so the session cookie stays
// same-origin with the pages.
const API = process.env.DATADRAFT_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default nextConfig;
