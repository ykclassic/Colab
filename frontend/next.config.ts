import type { NextConfig } from 'next';

const backendUrl = process.env.COLAB_BACKEND_URL ?? 'https://colab-api-rqoh.onrender.com';

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: '/backend/:path*',
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
