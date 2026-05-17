import json
import os
import urllib.request
import hashlib

UPSTREAM_URL = "https://raw.githubusercontent.com/zapplyjobs/Internships-2026/main/.github/data/current_jobs.json"
LOCAL_PATH = ".github/data/filtered_jobs.json"
NOTIFIED_PATH = ".github/data/notified_hashes.json"

SIBLING_HASH_URLS = [
    "https://raw.githubusercontent.com/skarazan/Summer2027-Internships/dev/.github/scripts/notified_hashes.json",
    "https://raw.githubusercontent.com/skarazan/Summer2026-Internships-NYC/dev/.github/scripts/notified_hashes.json",
    "https://raw.githubusercontent.com/skarazan/southeast-tech-internships-2026-2027/main/.github/data/notified_hashes.json",
]

def is_phd(entry):
    title = (entry.get("job_title") or "").lower()
    return "phd" in title or "ph.d" in title

def is_nyc_or_remote_usa(entry):
    city = (entry.get("job_city") or "").lower()
    loc = (entry.get("job_location") or "").lower()
    state = (entry.get("job_state") or "").lower()
    country = (entry.get("job_country") or "").lower()
    remote = entry.get("job_is_remote", False)

    # Reject UK locations
    if any(kw in loc or kw in city for kw in ("uk", "united kingdom", "london", "england", "scotland")):
        return False
    if country in ("gb", "uk", "united kingdom"):
        return False

    # NYC in-person/hybrid
    nyc_match = any(kw in city or kw in loc for kw in ("new york", "nyc", "manhattan", "brooklyn"))

    # Remote USA only
    remote_usa = False
    if remote:
        if country in ("us", "usa", "united states", ""):
            remote_usa = True
        # reject if explicitly non-US
        if any(kw in loc for kw in ("uk", "canada", "united kingdom", "london", "india", "europe")):
            remote_usa = False

    return nyc_match or remote_usa

def is_swe_or_data(entry):
    domains = [d.lower() for d in entry.get("tags", {}).get("domains", [])]
    return any(d in domains for d in ("software", "data_science"))

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
                data = json.loads(resp.read())
                hashes.update(data)
        except Exception:
            pass
    return hashes

print("Fetching upstream jobs...")
with urllib.request.urlopen(UPSTREAM_URL) as resp:
    upstream = json.loads(resp.read())

filtered = [e for e in upstream if is_swe_or_data(e) and is_nyc_or_remote_usa(e) and not is_phd(e)]
print(f"Upstream: {len(upstream)} -> Filtered (SWE/Data + NYC/Remote): {len(filtered)}")

old_filtered = load_json(LOCAL_PATH)
old_ids = {e.get("job_id") or e.get("fingerprint") for e in old_filtered}
old_by_id = {e.get("job_id") or e.get("fingerprint"): e for e in old_filtered}

new_ids = {e.get("job_id") or e.get("fingerprint") for e in filtered}
added = [e for e in filtered if (e.get("job_id") or e.get("fingerprint")) not in old_ids]

notified = set(load_json(NOTIFIED_PATH)) if os.path.exists(NOTIFIED_PATH) else set()
sibling_hashes = fetch_sibling_hashes()
all_known = notified | sibling_hashes

deduped = [e for e in added if job_hash(e) not in all_known]
skipped = len(added) - len(deduped)

print(f"New: {len(added)}, After dedup: {len(deduped)} (skipped {skipped} already notified by other repos)")

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
        loc = e.get("job_location") or f"{e.get('job_city', '')}, {e.get('job_state', '')}"
        if e.get("job_is_remote"):
            loc = "Remote" if not loc.strip(", ") else f"{loc} (Remote)"
        url = e.get("job_apply_link", "")
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
