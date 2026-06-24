/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ['7034-42-118-79-158.ngrok-free.app'],
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
}

export default nextConfig
