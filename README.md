# Random Prompt Generator
**Tagline:** *Where justice meets the machine.*

This repo powers a public podcast & site hosted on GitHub Pages. It publishes a ~15-minute daily brief on AI research/news relevant to criminal justice and corrections.

## Quick start
1. Add **GitHub Secrets** (Settings → Secrets and variables → Actions):
   - `SITE_BASE_URL` → e.g., `https://<username>.github.io/random-prompt-generator`
2. Enable **Pages** → Source: **GitHub Actions**.
3. Run the workflow **“Build & Deploy (Hello Episode)”** to publish a placeholder feed+episode and confirm everything works.
4. Later, add `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_IDS` to enable real audio generation.

## Structure (scaffold)
- `.github/workflows/daily.yml` — builds and deploys the site via GitHub Pages.
- `pipeline/hello_build.py` — creates a *placeholder* MP3 (3 seconds of silence), RSS feed, and an episode page.
- `site/` — output folder deployed to Pages.
- `LICENSE` — MIT for code.
- `CONTENT_LICENSE.md` — content is © Canto Chao (all rights reserved).
