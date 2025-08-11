import os, re, json, time, pathlib, datetime, itertools
import requests, xml.etree.ElementTree as ET, yaml

# ---- Settings ----
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "").rstrip("/")
TITLE = os.environ.get("PODCAST_TITLE", "Random Prompt Generator")
TAGLINE = os.environ.get("PODCAST_TAGLINE", "Where justice meets the machine.")
API_KEY = os.environ.get("ELEVENLABS_API_KEY")
VOICE_IDS = [v.strip() for v in os.environ.get("ELEVENLABS_VOICE_IDS", "").split(",") if v.strip()]
PROFILE_PATH = os.environ.get("PROFILE_PATH", "profiles/caleb.yaml")
MAX_RSS_ITEMS = int(os.environ.get("MAX_RSS_ITEMS", "50"))

assert SITE_BASE_URL, "Missing SITE_BASE_URL"
assert API_KEY, "Missing ELEVENLABS_API_KEY"
assert VOICE_IDS, "Missing ELEVENLABS_VOICE_IDS"
assert pathlib.Path(PROFILE_PATH).exists(), "Missing profile: {}".format(PROFILE_PATH)

profile = yaml.safe_load(open(PROFILE_PATH, "r", encoding="utf-8"))

INCL = set(x.lower() for x in profile.get("include_topics", []))
EXCL = set(x.lower() for x in profile.get("exclude_topics", []))
COND = set(x.lower() for x in profile.get("conditional_includes", []))
MAX_PAPERS = int(profile.get("max_papers_per_episode", 12))

site = pathlib.Path("site")
ep_dir = site / "episodes"
meta_dir = site / "meta"
site.mkdir(parents=True, exist_ok=True)
ep_dir.mkdir(parents=True, exist_ok=True)
meta_dir.mkdir(parents=True, exist_ok=True)

# ---- Data fetch ----
def fetch_arxiv(max_results=60):
    url = "http://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results={}".format(max_results)
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

# ---- Filtering ----
def passes_filter(p):
    text = (p.get("title","") + " " + p.get("summary","")).lower()
    if any(word in text for word in EXCL):
        return False
    inc_hit = any(word in text for word in INCL) if INCL else True
    cond_hit = any(word in text for word in COND) if COND else False
    return inc_hit or cond_hit

# ---- Utilities ----
def clean_filename(s, maxlen=80):
    s = re.sub(r"\s+", "-", s.strip().lower())
    s = re.sub(r"[^a-z0-9\-]+", "", s)
    s = s[:maxlen].strip("-")
    return s or "ep-{}".format(int(time.time()))

def tts(voice_id, text):
    url = "https://api.elevenlabs.io/v1/text-to-speech/{}".format(voice_id)
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
        raise RuntimeError("TTS failed: {} {}".format(r.status_code, r.text[:200]))
    return r.content

def build_script_short(p):
    title = (p.get("title") or "").strip()
    summary = (p.get("summary") or "").strip()
    summary = re.sub(r"\s+", " ", summary)
    first_sent = ""
    if summary:
        parts = re.split(r"(?<=[.!?])\s+", summary)
        first_sent = parts[0] if parts else summary
    intro = "Today's deep dive. Here's the short version first, then why it matters."
    why = "In plain language, this paper explores ideas that could affect how AI shows up in the real world."
    outro = "Links are in the show notes. Thanks for listening."
    # Short, punctuation-friendly script
    script = "{} Title: {}. {} {} {}".format(intro, title, first_sent, why, outro)
    return script

def xml_escape(s):
    return (s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
              .replace('"',"&quot;").replace("'","&apos;"))

# ---- Build list ----
papers = [p for p in fetch_arxiv() if passes_filter(p)]
papers = papers[:MAX_PAPERS]

if not papers:
    papers = [{
        "title": "No matching papers today",
        "summary": "No cs.AI entries matched your profile.",
        "link": SITE_BASE_URL,
        "authors": []
    }]

generated_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
date_label = datetime.date.today().isoformat()
created_items = []

# ---- Per-paper episodes ----
for i, (p, voice_id) in enumerate(zip(papers, itertools.cycle(VOICE_IDS)), 1):
    title = (p.get("title") or "").strip() or "Paper {}".format(i)
    slug_base = clean_filename(title or "paper-{}".format(i))
    slug = "{}-{}".format(date_label, slug_base)
    build_id = "{}-{}".format(int(time.time()), i)

    script_text = build_script_short(p)
    mp3_bytes = tts(voice_id, script_text)
    mp3_path = ep_dir / "{}.mp3".format(slug)
    mp3_path.write_bytes(mp3_bytes)

    meta = {
        "title": "Deep Dive - {}".format(title),
        "slug": slug,
        "generated_at_utc": generated_at,
        "build_id": build_id,
        "audio_url": "{}/episodes/{}".format(SITE_BASE_URL, mp3_path.name),
        "audio_file": "episodes/{}".format(mp3_path.name),
        "filesize": mp3_path.stat().st_size,
        "paper": {
            "title": title,
            "link": p.get("link",""),
            "authors": p.get("authors", [])
        }
    }
    (meta_dir / "{}.json".format(slug)).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    created_items.append(meta)

    # Append to homepage card-by-card
    index = site / "index.html"
    if index.exists():
        html = index.read_text(encoding="utf-8").replace("\\n", "\n")
        notes_html = '<ul><li><a href="{link}">{title}</a></li></ul>'.format(link=p.get("link",""), title=title)
        audio_html = (
            '\n<div class="episode">\n'
            '  <h3>Deep Dive - {title}</h3>\n'
            '  <div class="text-sm" style="opacity:.7">Generated at {gen} • build {bid}</div>\n'
            '  <audio controls src="episodes/{file}"></audio>\n'
            '  {notes}\n'
            '</div>\n'
        ).format(title=title, gen=generated_at, bid=build_id, file=mp3_path.name, notes=notes_html)
        html = html.replace("</main>", "\n" + audio_html + "\n</main>")
        index.write_text(html, encoding="utf-8")

# ---- Rebuild RSS ----
metas = []
for f in sorted(meta_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_RSS_ITEMS]:
    metas.append(json.loads(f.read_text(encoding="utf-8")))

items_xml_parts = []
now_rfc2822 = datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
for m in metas:
    item = []
    item.append("        <item>")
    item.append("          <title>{}</title>".format(xml_escape(m["title"])))
    item.append("          <description>{}</description>".format(xml_escape("Generated at {} (build {}).".format(m["generated_at_utc"], m["build_id"]))))
    item.append("          <pubDate>{}</pubDate>".format(now_rfc2822))
    item.append('          <enclosure url="{}" length="{}" type="audio/mpeg"/>'.format(xml_escape(m["audio_url"]), m["filesize"]))
    item.append('          <guid isPermaLink="false">{}</guid>'.format(xml_escape(m["slug"])))
    item.append("        </item>")
    items_xml_parts.append("\n".join(item))

rss = []
rss.append('<?xml version="1.0" encoding="UTF-8"?>')
rss.append('<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">')
rss.append('  <channel>')
rss.append('    <title>{}</title>'.format(xml_escape(TITLE)))
rss.append('    <link>{}</link>'.format(xml_escape(SITE_BASE_URL)))
rss.append('    <description>{}</description>'.format(xml_escape(TAGLINE)))
rss.append('    <language>en-us</language>')
rss.append('    <itunes:author>Canto Chao</itunes:author>')
rss.append('    <itunes:summary>{}</itunes:summary>'.format(xml_escape(TAGLINE)))
rss.append('    <itunes:explicit>false</itunes:explicit>')
rss.append("\n".join(items_xml_parts))
rss.append('  </channel>')
rss.append('</rss>')
(site / "podcast.xml").write_text("\n".join(rss) + "\n", encoding="utf-8")

# Quick build status file
(site / "last_build.json").write_text(json.dumps({
    "generated_at_utc": generated_at,
    "created_count": len(created_items),
    "created_slugs": [m["slug"] for m in created_items]
}, indent=2), encoding="utf-8")

print("Created {} episode(s).".format(len(created_items)))
