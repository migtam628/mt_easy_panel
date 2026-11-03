import type { NextConfig } from "next";

// No Next.js server, route handlers, middleware, or server-side auth.
// The existing FastAPI process owns authentication, authorization and /api.
// The exported assets will eventually be served under this exact prefix.
const nextConfig: NextConfig = {
  output: "export",
  basePath: "/next-preview",
  trailingSlash: true,
  poweredByHeader: false,
  images: { unoptimized: true },
};

export default nextConfig;
