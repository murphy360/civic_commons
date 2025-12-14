/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  
  // Transpile shared packages
  transpilePackages: ['@civic-commons/shared'],
  
  env: {
    NEXT_PUBLIC_APP_NAME: 'Civic Commons Admin',
  },
  
  experimental: {
    serverActions: {
      bodySizeLimit: '2mb',
    },
  },
};

module.exports = nextConfig;
