import withPWAInit from "next-pwa";

const withPWA = withPWAInit({
  dest: "public",
  // PWA service worker is generated for production builds only.
  disable: process.env.NODE_ENV === "development",
  register: true,
  skipWaiting: true,
});

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Standalone output so the Docker image stays small.
  output: "standalone",
};

export default withPWA(nextConfig);
