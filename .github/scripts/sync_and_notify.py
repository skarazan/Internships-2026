import json
import os
import re
import urllib.request
import hashlib

UPSTREAM_URL = "https://raw.githubusercontent.com/zapplyjobs/Internships-2026/main/README.md"
LOCAL_PATH = ".github/data/filtered_jobs.json"
NOTIFIED_PATH = ".github/data/notified_hashes.json"

# Only scrape these category sections from the upstream README
WANTED_SECTIONS = ("Software Engineering", "Data Science & AI")

SIBLING_HASH_URLS = [
    "https://raw.githubusercontent.com/skarazan/Summer2027-Internships/dev/.github/scripts/notified_hashes.json",
    "https://raw.githubusercontent.com/skarazan/Summer2026-Internships-NYC/dev/.github/scripts/notified_hashes.json",
    "https://raw.githubusercontent.com/skarazan/southeast-tech-internships-2026-2027/main/.github/data/notified_hashes.json",
    "https://raw.githubusercontent.com/skarazan/jsearch-internship-scanner/main/.github/data/notified_hashes.json",
]

# Matches a markdown table row ending in an Apply image link:
# | **Company** | Role | Location | Posted | Visa | [<img...>](url) |
ROW_RE = re.compile(
    r"^\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.*?)\s*\|\s*\[.*?\]\((https?://[^)]+)\)\s*\|\s*$"
)
SUMMARY_RE = re.compile(r"<summary>.*?<strong>(.+?)</strong>", re.IGNORECASE)

NON_US_KEYWORDS = ("uk", "united kingdom", "london", "england", "scotland",
                   "ireland", "canada", "india", "europe", "germany", "munich",
                   "toronto", "chennai", "hyderabad", "telangana", "tamil nadu")

def clean(s):
    return s.replace("...", "").strip()

def is_phd(title):
    t = title.lower()
    return "phd" in t or "ph.d" in t

def is_nyc_or_remote_usa(loc):
    l = loc.lower()
    if any(kw in l for kw in NON_US_KEYWORDS):
        return False
    nyc = any(kw in l for kw in ("new york", "nyc", "brooklyn"))
    if "manhattan" in l and "beach" not in l:
        nyc = True
    remote_usa = "remote" in l  # non-US already rejected above
    return nyc or remote_usa

def parse_readme(text):
    """Parse the upstream README, returning entries from wanted sections only."""
    entries = []
    current_section = None
    for line in text.splitlines():
        m = SUMMARY_RE.search(line)
        if m:
            current_section = m.group(1).strip()
            continue
        if current_section not in WANTED_SECTIONS:
            continue
        row = ROW_RE.match(line)
        if not row:
            continue
        company, role, location, _posted, _visa, url = row.groups()
        entries.append({
            "employer_name": clean(company),
            "job_title": clean(role),
            "job_location": clean(location),
            "job_apply_link": url.strip(),
            "job_id": url.strip(),  # apply URL is the stable unique id
            "section": current_section,
        })
    return entries

def job_hash(entry):
    key = f"{entry.get('employer_name','').lower().strip()}|{entry.get('job_title','').lower().strip()}"
    return hashlib.md5(key.encode()).hexdigest()[:12]

def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def fetch_sibling_hashes():
    hashes = set()
    for url in SIBLING_HASH_URLS:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                hashes.update(json.loads(resp.read()))
        except Exception:
            pass
    return hashes

if __name__ == "__main__":
    print("Fetching upstream README...")
    req = urllib.request.Request(UPSTREAM_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        text = resp.read().decode("utf-8")

    parsed = parse_readme(text)
    filtered = [
        e for e in parsed
        if is_nyc_or_remote_usa(e["job_location"])
        and not is_phd(e["job_title"])
    ]
    print(f"Parsed (SWE/Data): {len(parsed)} -> Filtered (NYC/Remote USA - no PhD): {len(filtered)}")

    old_filtered = load_json(LOCAL_PATH)
    old_ids = {e.get("job_id") for e in old_filtered}
    added = [e for e in filtered if e["job_id"] not in old_ids]

    notified = set(load_json(NOTIFIED_PATH)) if os.path.exists(NOTIFIED_PATH) else set()
    sibling_hashes = fetch_sibling_hashes()
    all_known = notified | sibling_hashes

    deduped = [e for e in added if job_hash(e) not in all_known]
    skipped = len(added) - len(deduped)
    print(f"New: {len(added)}, After dedup: {len(deduped)} (skipped {skipped} already notified)")

    os.makedirs(os.path.dirname(LOCAL_PATH), exist_ok=True)
    with open(LOCAL_PATH, "w") as f:
        json.dump(filtered, f, indent=2)

    output_file = os.environ.get("GITHUB_OUTPUT", "/dev/null")
    if deduped:
        for e in deduped:
            notified.add(job_hash(e))
        with open(NOTIFIED_PATH, "w") as f:
            json.dump(sorted(notified), f)

        MAX_SHOW = 5
        lines = []
        for e in deduped[:MAX_SHOW]:
            loc = e["job_location"]
            url = e["job_apply_link"]
            lines.append(f"🆕 **{e['employer_name']}** — {e['job_title']}\n📍 {loc}\n🔗 <{url}>")
        extra = len(deduped) - len(lines)
        if extra > 0:
            lines.append(f"...and **{extra} more** — check the README")
        message = "@everyone\n\n" + "\n\n".join(lines)
        with open(".github/scripts/discord_message.txt", "w") as f:
            f.write(message)
        with open(output_file, "a") as f:
            f.write("has_changes=true\n")
    else:
        with open(output_file, "a") as f:
            f.write("has_changes=false\n")
        print("No new listings to notify.")
