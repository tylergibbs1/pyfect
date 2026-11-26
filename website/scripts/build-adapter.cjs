// A Next.js adapter that changes nothing. Vercel builds with its own adapter (NEXT_ADAPTER_PATH),
// and any adapter moves prerendered bodies from .next/server/app to .next/server/route-cache;
// the docs workflow builds with this one so CI's build has the layout Vercel's has, and a
// postbuild check that reads the old path fails in CI instead of only on Vercel.
module.exports = {
  name: 'pyfect-docs-ci',
  async modifyConfig(config) {
    return config;
  },
  async onBuildComplete() {},
};
