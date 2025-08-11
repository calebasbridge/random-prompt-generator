
# pipeline/build_daily.py
import os, re, json, time, pathlib, datetime, subprocess, itertools, hashlib
import requests, xml.etree.ElementTree as ET, yaml

# --- Settings (from env and profile) ---
SITE_BASE_URL = os.environ.get("SITE_BASE_URL","").rstrip("/")
TITLE = os.environ.get("PODCAST_TITLE","Random Prompt Generator")
TAGLINE = os.environ.get("PODCAST_TAGLINE","Where justice meets the machine.")
API_KEY = os.environ.get("ELEVENLABS_API_KEY")
VOICE_IDS = [v.strip() for v in os.environ.get("ELEVENLABS_VOICE_IDS","").split(",") if v.strip()]
PROFILE_PATH = os.environ.get("PROFILE_PATH","profiles/caleb.yaml")
MAX_RSS_ITEMS = int(os.environ.get("MAX_RSS_ITEMS","50"))  # keep last N in feed

assert SITE_BASE_URL, "Missing SITE_BASE_URL"
assert API_KEY, "Missing ELEVENLABS_API_KEY"
assert VOICE_IDS, "Missing ELEVENLABS_VOICE_IDS"
assert pathlib.Path(PROFILE_PATH).exists(), f"Missing profile: {PROFILE_PATH}"

profile = yaml.safe_load(open(PROFILE_PATH, "r", encoding="utf-8"))

INCL = set(x.lower() for x in profile.get("include_topics", []))
EXCL = set(x.lower() for x in profile.get("exclude_topics", []))
COND = set(x.lower() for x in profile.get("conditional_includes", []))
# MAX_PAPERS still used as a soft cap even though we do per-paper episodes
MAX_PAPERS = int(profile.get("max_papers_per_episode", 12))

site = pathlib.Path("site")
ep_dir = site / "episodes"
meta_dir = site / "meta"
site.mkdir(parents=True, exist_ok=True)
ep_dir.mkdir(parents=True, exist_ok=True)
meta_dir.mkdir(parents=True, exist_ok=True)

# --- Helpers ---
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
    text = (p.get("title","") + " " + p.get("summary","")).lower()
    if any(word in text for word in EXCL):
        return False
    inc_hit = any(word in text for word in INCL) if INCL else True
    cond_hit = any(word in text for word in COND) if COND else False
    return inc_hit or cond_hit

def clean_filename(s, maxlen=80):
    s = re.sub(r"\s+", "-", s.strip().lower())
    s = re.sub(r"[^a-z0-9\-]+", "", s)
    return s[:maxlen].strip("-") or f"ep-{int(time.time())}"

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

# Very simple script template (we'll improve prose/pauses next step)
def build_script(p):
    title = p["title"].strip()
    intro = (
        "Today’s deep dive. "
        "Here’s the short version first—then why it matters."
    )
    summary = p["summary"].strip()
    summary = re.sub(r"\s+", " ", summary)
    first_sent = re.split(r"(?<=[.!?])\s+", summary)[0] if summary else ""
    why = "In plain language, this paper explores ideas that could affect how AI shows up in the real world."
    outro = "Links are in the show notes. Thanks for listening."
    script = f"{intro} Title: {title}. {first_sent} {why} {outro}"
    return script

# --- Build list of candidate papers ---
papers = [p for p in fetch_arxiv() if passes_filter(p)]
papers = papers[:MAX_PAPERS]  # soft cap

if not papers:
    papers = [{"title": "No matching papers today",
               "summary": "No cs.AI entries matched your profile.",
               "link": SITE_BASE_URL, "authors": []}]

# --- Per-paper episodes ---
generated_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
date_label = datetime.date.today().isoformat()

created_items = []  # for RSS

for i, (p, voice_id) in enumerate(zip(papers, itertools.cycle(VOICE_IDS)), 1):
    title = p["title"].strip() or f"Paper {i}"
    slug_base = clean_filename(title or f"paper-{i}")
    slug = f"{date_label}-{slug_base}"
    build_id = f"{int(time.time())}-{i}"

    # Script -> MP3
    script_text = build_script(p)
    mp3_bytes = tts(voice_id, script_text)
    mp3_path = ep_dir / f"{slug}.mp3"
    mp3_path.write_bytes(mp3_bytes)

    # Per-episode metadata
    meta = {
        "title": f"Deep Dive — {title}",
        "slug": slug,
        "generated_at_utc": generated_at,
        "build_id": build_id,
        "audio_url": f"{SITE_BASE_URL}/episodes/{mp3_path.name}",
        "audio_file": f"episodes/{mp3_path.name}",
        "filesize": mp3_path.stat().st_size,
        "paper": {
            "title": title,
            "link": p.get("link",""),
            "authors": p.get("authors", [])
        }
    }
    (meta_dir / f"{slug}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    created_items.append(meta)

    # Append to homepage
    index = site / "index.html"
    if index.exists():
        notes_html = f'<ul><li><a href="{p.get("link","")}">{title}</a></li></ul>'
        audio_html = f'''
<div class="episode">
  <h3>Deep Dive — {title}</h3>
  <div class="text-sm" style="opacity:.7">Generated at {generated_at} • build {build_id}</div>
  <audio controls src="episodes/{mp3_path.name}"></audio>
  {notes_html}
</div>
'''
        html = index.read_text(encoding="utf-8")
        html = html.replace("</main>", f"\\n{audio_html}\\n</main>")
        index.write_text(html, encoding="utf-8")

# --- Rebuild RSS from meta files (keep latest N) ---
# Read all meta files and sort by file mtime desc
metas = []
for f in sorted(meta_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_RSS_ITEMS]:
    metas.append(json.loads(f.read_text(encoding="utf-8")))

def xml_escape(s: str) -> str:
    return (s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
              .replace('"',"&quot;").replace("'","&apos;"))

items_xml_parts = []
for m in metas:
    items_xml_parts.append(
        "        <item>\\n"
        f"          <title>{xml_escape(m['title'])}</title>\\n"
        f"          <description>{xml_escape('Generated at ' + m['generated_at_utc'] + ' (build ' + m['build_id'] + ').')}</description>\\n"
        f"          <pubDate>{datetime.datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>\\n"
        f"          <enclosure url=\"{xml_escape(m['audio_url'])}\" length=\"{m['filesize']}\" type=\"audio/mpeg\"/>\\n"
        f"          <guid isPermaLink=\"false\">{xml_escape(m['slug'])}</guid>\\n"
        "        </item>"
    )

rss = (
    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\\n"
    "<rss version=\"2.0\" xmlns:itunes=\"http://www.itunes.com/dtds/podcast-1.0.dtd\">\\n"
    "  <channel>\\n"
    f"    <title>{xml_escape(TITLE)}</title>\\n"
    f"    <link>{xml_escape(SITE_BASE_URL)}</link>\\n"
    f"    <description>{xml_escape(TAGLINE)}</description>\\n"
    "    <language>en-us</language>\\n"
    "    <itunes:author>Canto Chao</itunes:author>\\n"
    f"    <itunes:summary>{xml_escape(TAGLINE)}</itunes:summary>\\n"
    "    <itunes:explicit>false</itunes:explicit>\\n"
    + "\\n".join(items_xml_parts) + "\\n"
    "  </channel>\\n"
    "</rss>\\n"
)

(site / "podcast.xml").write_text(rss, encoding="utf-8")

# Also write a small last_build.json for quick checks
(site / "last_build.json").write_text(
    json.dumps({
        "generated_at_utc": generated_at,
        "created_count": len(created_items),
        "created_slugs": [m["slug"] for m in created_items]
    }, indent=2),
    encoding="utf-8"
)

print(f"Created {len(created_items)} episode(s).")
