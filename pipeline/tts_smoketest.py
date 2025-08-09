# pipeline/tts_smoketest.py
import os, json, time, pathlib, requests, datetime, itertools, subprocess

SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "").rstrip("/")
TITLE = os.environ.get("PODCAST_TITLE","Random Prompt Generator")
TAGLINE = os.environ.get("PODCAST_TAGLINE","Where justice meets the machine.")
API_KEY = os.environ.get("ELEVENLABS_API_KEY")
VOICE_IDS = [v for v in os.environ.get("ELEVENLABS_VOICE_IDS","").split(",") if v]

assert API_KEY, "Missing ELEVENLABS_API_KEY"
assert VOICE_IDS, "Missing ELEVENLABS_VOICE_IDS (comma-separated)"
assert SITE_BASE_URL, "Missing SITE_BASE_URL"

site = pathlib.Path("site"); ep_dir = site / "episodes"
site.mkdir(parents=True, exist_ok=True); ep_dir.mkdir(parents=True, exist_ok=True)

# Tiny “papers” just for rotation demo (each 'paper' gets a different voice)
papers = [
    "Paper 1 — This is a test line to confirm Text-to-Speech works.",
    "Paper 2 — Rotating to the second voice for this sample sentence.",
    "Paper 3 — Third voice reading, per-paper rotation confirmed.",
    "Paper 4 — Fourth voice completes the rotation. Nice."
]

def tts(voice_id: str, text: str) -> bytes:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": API_KEY,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }
    data = {
        "model_id": "eleven_multilingual_v2",
        "text": text,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
    }
    r = requests.post(url, headers=headers, data=json.dumps(data), timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"TTS failed: {r.status_code} {r.text[:200]}")
    return r.content

# Stitch 4 short clips (one per voice/paper) into one MP3
clips = []
for text, voice_id in zip(papers, itertools.cycle(VOICE_IDS)):
    mp3_bytes = tts(voice_id, text)
    clip_path = ep_dir / f"clip_{len(clips)+1}.mp3"
    clip_path.write_bytes(mp3_bytes)
    clips.append(clip_path)

episode_mp3 = ep_dir / "smoketest.mp3"

# Use ffmpeg to concat MP3s safely
# Build a concat list file
concat_list = ep_dir / "concat.txt"
concat_list.write_text("\n".join(f"file '{p.name}'" for p in clips), encoding="utf-8")

# Convert to a uniform format then concat
# (re-encode each clip to ensure seamless concat)
reenc = []
for i, p in enumerate(clips, 1):
    outp = ep_dir / f"re_{i}.mp3"
    subprocess.run([
        "ffmpeg","-y","-i",str(p),
        "-ar","44100","-ac","2","-b:a","160k",
        str(outp)
    ], check=True)
    reenc.append(outp)

concat_list.write_text("\n".join(f"file '{p.name}'" for p in reenc), encoding="utf-8")
subprocess.run([
    "ffmpeg","-y","-f","concat","-safe","0","-i",str(concat_list),
    "-c","copy", str(episode_mp3)
], check=True)

# Minimal RSS that points to the new MP3
now = datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{TITLE}</title>
    <link>{SITE_BASE_URL}</link>
    <description>{TAGLINE}</description>
    <language>en-us</language>
    <itunes:author>Canto Chao</itunes:author>
    <itunes:summary>{TAGLINE}</itunes:summary>
    <itunes:explicit>false</itunes:explicit>

    <item>
      <title>ElevenLabs Smoke Test</title>
      <description>Four short lines read by four rotating voices (per-paper style).</description>
      <pubDate>{now}</pubDate>
      <enclosure url="{SITE_BASE_URL}/episodes/smoketest.mp3" length="{episode_mp3.stat().st_size}" type="audio/mpeg"/>
      <guid isPermaLink="false">smoketest-{int(time.time())}</guid>
    </item>
  </channel>
</rss>
"""
(site / "podcast.xml").write_text(rss, encoding="utf-8")

# Update index page with a link to the smoketest
index = (site / "index.html")
extra = '\n<p><a href="episodes/smoketest.mp3">Download the ElevenLabs smoke test MP3</a></p>\n'
if index.exists():
    index.write_text(index.read_text(encoding="utf-8").replace("</main>", extra + "</main>"), encoding="utf-8")

print("Smoke test built:", episode_mp3)
