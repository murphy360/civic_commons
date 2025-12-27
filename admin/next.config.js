/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  
  // Enable instrumentation hook for startup logging
  experimental: {
    instrumentationHook: true,
    serverActions: {
      bodySizeLimit: '2mb',
    },
  },
  
  // Transpile shared packages
  transpilePackages: ['@civic-commons/shared'],
  
  env: {
    NEXT_PUBLIC_APP_NAME: 'Civic Commons Admin',
  },
};

module.exports = nextConfig;
