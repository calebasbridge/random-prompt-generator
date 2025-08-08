import os, datetime, subprocess, pathlib

SITE = pathlib.Path("site")
EP_DIR = SITE / "episodes"
EP_DIR.mkdir(parents=True, exist_ok=True)

# Create a tiny placeholder mp3 (3s silence) using ffmpeg
mp3_path = EP_DIR / "placeholder.mp3"
if not mp3_path.exists():
    # Generate 3 seconds of silence and encode to mp3
    # Requires ffmpeg in the Actions runner
    cmd = [
        "ffmpeg",
        "-f","lavfi","-i","anullsrc=r=44100:cl=mono",
        "-t","3",
        "-q:a","9",
        str(mp3_path)
    ]
    subprocess.run(cmd, check=True)

# Build a minimal podcast RSS (podcast.xml)
base_url = os.environ.get("SITE_BASE_URL", "").rstrip("/")
title = os.environ.get("PODCAST_TITLE","Random Prompt Generator")
tagline = os.environ.get("PODCAST_TAGLINE","Where justice meets the machine.")
now = datetime.datetime.utcnow()

rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{title}</title>
    <link>{base_url}</link>
    <description>{tagline}</description>
    <language>en-us</language>
    <itunes:author>Canto Chao</itunes:author>
    <itunes:summary>{tagline}</itunes:summary>
    <itunes:explicit>false</itunes:explicit>

    <item>
      <title>Placeholder Episode</title>
      <description>Scaffold test episode.</description>
      <pubDate>{now.strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate>
      <enclosure url="{base_url}/episodes/placeholder.mp3" length="{(EP_DIR/'placeholder.mp3').stat().st_size}" type="audio/mpeg"/>
      <guid isPermaLink="false">placeholder-{now.strftime("%Y%m%d%H%M%S")}</guid>
    </item>
  </channel>
</rss>"""

(SITE / "podcast.xml").write_text(rss, encoding="utf-8")

# Also write a simple per-episode page
episode_html = """<!doctype html>
<html><head><meta charset="utf-8"><title>Placeholder Episode</title></head>
<body>
  <h1>Placeholder Episode</h1>
  <p>This is a scaffold to verify your podcast feed and audio hosting on GitHub Pages.</p>
  <audio controls src="placeholder.mp3"></audio>
  <p><a href="../index.html">Back to index</a></p>
</body></html>
"""
(EP_DIR / "placeholder.html").write_text(episode_html, encoding="utf-8")

print("Scaffold build complete.")
