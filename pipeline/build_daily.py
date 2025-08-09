# pipeline/build_daily.py
import os, re, json, time, pathlib, datetime, subprocess, itertools
import requests, xml.etree.ElementTree as ET, yaml

SITE_BASE_URL = os.environ.get("SITE_BASE_URL","").rstrip("/")
TITLE = os.environ.get("PODCAST_TITLE","Random Prompt Generator")
TAGLINE = os.environ.get("PODCAST_TAGLINE","Where justice meets the machine.")
API_KEY = os.environ.get("ELEVENLABS_API_KEY")
VOICE_IDS = [v for v in os.environ.get("ELEVENLABS_VOICE_IDS","").split(",") if v]
PROFILE_PATH = os.environ.get("PROFILE_PATH","profiles/caleb.yaml")

assert SITE_BASE_URL, "Missing SITE_BASE_URL"
assert API_KEY, "Missing ELEVENLABS_API_KEY"
assert VOICE_IDS, "Missing ELEVENLABS_VOICE_IDS"
assert pathlib.Path(PROFILE_PATH).exists(), f"Missing profile: {PROFILE_PATH}"

profile = yaml.safe_load(open(PROFILE_PATH, "r", encoding="utf-8"))

INCL = set(x.lower() for x in profile.get("include_topics", []))
EXCL = set(x.lower() for x in profile.get("exclude_topics", []))
COND = set(x.lower() for x in profile.get("conditional_includes", []))
MAX_PAPERS = int(profile.get("max_papers_per_episode", 12))

site = pathlib.Path("site"); ep_dir = site / "episodes"
site.mkdir(parents=True, exist_ok=True); ep_dir.mkdir(parents=True, exist_ok=True)

def fetch_arxiv(max_results=60):
    url = (
        "http://export.arxiv.org/api/query?"
        "search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=" + str(max_results)
    )
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(r.text)
    items = []
    for entry in root.findall("atom:entry", ns):
        title = entry.findtext("atom:title", default="", namespaces=ns).strip()
        summary = entry.findtext("atom:summary", default="", namespaces=ns).strip()
        link = None
        for l in entry.findall("atom:link", ns):
            if l.attrib.get("type") == "text/html":
                link = l.attrib.get("href")
        if not link:
            link = entry.findtext("atom:id", default="", namespaces=ns)
        authors = [a.findtext("atom:name", default="", namespaces=ns) for a in entry.findall("atom:author", ns)]
        items.append({"title": title, "summary": summary, "link": link, "authors": authors})
    return items

def passes_filter(p):
    text = (p["title"] + " " + p["summary"]).lower()
    if any(word in text for word in EXCL):
        return False
    inc_hit = any(word in text for word in INCL)
    cond_hit = any(word in text for word in COND)
    return inc_hit or cond_hit

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
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    r = requests.post(url, headers=headers, data=json.dumps(data), timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"TTS failed: {r.status_code} {r.text[:200]}")
    return r.content

def blurb(p):
    # Very simple first pass—later we'll swap in a tighter summarizer
    first_sent = re.split(r"(?<=[.!?])\s+", p["summary"].strip()).pop(0) if p["summary"].strip() else ""
    return f"{p['title']}. {first_sent} Link available in show notes."

# 1) fetch + filter
papers = [p for p in fetch_arxiv() if passes_filter(p)]
papers = papers[:MAX_PAPERS]  # cap

if not papers:
    papers = [{"title": "No matching papers today",
               "summary": "No cs.AI entries matched your profile.",
               "link": SITE_BASE_URL, "authors": []}]

# 2) build per-paper clips with rotating voices
clips = []
for i, (p, voice_id) in enumerate(zip(papers, itertools.cycle(VOICE_IDS)), 1):
    text = blurb(p)
    mp3 = tts(voice_id, text)
    clip_path = ep_dir / f"paper_{i}.mp3"
    clip_path.write_bytes(mp3)
    clips.append(clip_path)

# 3) Re-encode for safe concat, then stitch
reenc = []
for i, p in enumerate(clips, 1):
    outp = ep_dir / f"re_{i}.mp3"
    subprocess.run([
        "ffmpeg","-y","-i",str(p),
        "-ar","44100","-ac","2","-b:a","160k",
        str(outp)
    ], check=True)
    reenc.append(outp)

episode_mp3 = ep_dir / f"episode_{int(time.time())}.mp3"
concat_list = ep_dir / "concat.txt"
concat_list.write_text("\n".join(f"file '{p.name}'" for p in reenc), encoding="utf-8")
subprocess.run([
    "ffmpeg","-y","-f","concat","-safe","0","-i",str(concat_list),
    "-c","copy", str(episode_mp3)
], check=True)

# 4) write show notes & update index with a player
notes = ["<ul>"]
for p in papers:
    notes.append(f'<li><a href="{p["link"]}">{p["title"]}</a></li>')
notes.append("</ul>")
notes_html = "\n".join(notes)

index = site / "index.html"
if index.exists():
    date_label = datetime.date.today().isoformat()
    audio_html = f'''
<div class="episode">
  <h3>Daily Brief — {date_label}</h3>
  <p>Rotating voices per paper. Show notes below.</p>
  <audio controls src="episodes/{episode_mp3.name}"></audio>
  {notes_html}
</div>
'''
    html = index.read_text(encoding="utf-8")
    html = html.replace("</main>", f"\n{audio_html}\n</main>")
    index.write_text(html, encoding="utf-8")

# 5) update RSS with the new episode
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
      <title>Daily Brief — {datetime.date.today().isoformat()}</title>
      <description>Auto-generated episode. Show notes on site.</description>
      <pubDate>{now}</pubDate>
      <enclosure url="{SITE_BASE_URL}/episodes/{episode_mp3.name}" length="{episode_mp3.stat().st_size}" type="audio/mpeg"/>
      <guid isPermaLink="false">{episode_mp3.stem}</guid>
    </item>
  </channel>
</rss>
"""
(site / "podcast.xml").write_text(rss, encoding="utf-8")
print("Episode built:", episode_mp3)
