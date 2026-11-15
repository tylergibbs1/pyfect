import { createMDX } from 'fumadocs-mdx/next';

const withMDX = createMDX();

/** @type {import('next').NextConfig} */
const config = {
  reactStrictMode: true,
  experimental: {
    // A page that fails or times out fails the build. Next retries it by default, which
    // once hid pages taking over a minute each.
    staticGenerationRetryCount: 0,
  },
  async redirects() {
    return [
      { source: '/', destination: '/docs', permanent: false },
      // The upgrade page's first URL, which advisories link to.
      {
        source: '/docs/eventlog-upgrade-0-6-7',
        destination: '/docs/eventlog-upgrade',
        permanent: true,
      },
      {
        source: '/docs/eventlog-upgrade-0-6-7.md',
        destination: '/docs/eventlog-upgrade.md',
        permanent: true,
      },
    ];
  },
};

export default withMDX(config);
