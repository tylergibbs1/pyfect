- The sitemap dates every guide again. The dates came from git history, which Vercel's build
  clone doesn't have, so the live sitemap dated none of them. They now come from
  `website/lib/page-dates.json`, which records when each guide, or a snippet or diagram it
  shows, last changed; a test fails when an edit leaves it stale, and the build fails if a
  guide goes out undated. API reference pages stay undated. `/` now redirects to `/docs`
  permanently (308).
