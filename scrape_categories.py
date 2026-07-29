#!/usr/bin/env python3
"""
Scrape the breadcrumb "primary category" for each cited URL (POLITE version).
=============================================================================
Reads unique ranking URLs (from data.json, else newest export), fetches each
page slowly to avoid rate limits, extracts the breadcrumb category
(Home > Document Management > ... -> "Document Management"), and writes
url_categories.json (URL -> category) that build_from_export.py joins on.

Rate-limit safe: low concurrency, pause between requests, browser user-agent,
and automatic wait-and-retry on HTTP 429. Slower but reliable.
INCREMENTAL: only fetches URLs not already saved (and re-tries past 429/errors),
so if it gets interrupted, just run it again to finish the rest.

USAGE
  pip install requests beautifulsoup4 pandas openpyxl
  python3 scrape_categories.py --sample 10   # quick test, prints results
  python3 scrape_categories.py               # full run -> url_categories.json
"""
import os, sys, json, glob, time, random, html
from bs4 import BeautifulSoup
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "url_categories.json")
PRE = "https://www.saasworthy.com"  # display hint only
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# --- tuning (conservative to avoid 429) ---
WORKERS      = 2      # low concurrency
DELAY        = 1.2    # seconds between requests per worker
MAX_RETRIES  = 4
BACKOFF      = 20     # base seconds to wait on a 429

session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com/",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-User": "?1",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Connection": "keep-alive",
})

def pick(names):
    names = [n for n in names if n]
    if names and names[0].lower() == "home": names = names[1:]
    if len(names) >= 2: return names[-2]
    if len(names) == 1: return names[0]
    return None

def extract_category(page):
    soup = BeautifulSoup(page, "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):
        try: data = json.loads(tag.string or "")
        except Exception: continue
        for block in (data if isinstance(data, list) else [data]):
            graph = block.get("@graph", [block]) if isinstance(block, dict) else [block]
            for node in graph:
                if isinstance(node, dict) and node.get("@type") == "BreadcrumbList":
                    names = []
                    for it in sorted(node.get("itemListElement", []), key=lambda x: x.get("position", 0)):
                        nm = it.get("name")
                        if not nm and isinstance(it.get("item"), dict): nm = it["item"].get("name")
                        if nm: names.append(html.unescape(str(nm).strip()))
                    c = pick(names)
                    if c: return c
    for sel in ['[class*="breadcrumb"]', 'nav[aria-label*="readcrumb"]', 'ol.breadcrumb', 'ul.breadcrumb']:
        el = soup.select_one(sel)
        if el:
            raw = [a.get_text(strip=True) for a in el.find_all(["a","span","li"])]
            seen = []
            for n in raw:
                if n and (not seen or seen[-1] != n): seen.append(html.unescape(n))
            c = pick(seen)
            if c: return c
    return "Uncategorized"

def fetch(url):
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(url, timeout=25)
            if r.status_code == 200:
                return extract_category(r.text)
            if r.status_code in (429, 403, 503):
                # blocked/throttled — wait and retry with a longer pause
                wait = BACKOFF * (attempt + 1) + random.uniform(0, 5)
                time.sleep(wait); continue
            return f"HTTP {r.status_code}"
        except Exception:
            time.sleep(5 * (attempt + 1))
    return "HTTP 403"

def unique_urls():
    """Union of every ranking URL we can find — from all exports AND data.json.
    Reads exports first because the repo's data.json can be stale (rebuilt only
    at deploy time and not committed back)."""
    urls = set()
    # 1) every Ahrefs export in the repo (root and exports/)
    patterns = ("*.xlsx", "*.xls", "*.csv", "exports/*.xlsx", "exports/*.xls", "exports/*.csv")
    files = sum([glob.glob(os.path.join(HERE, p)) for p in patterns], [])
    if files:
        import pandas as pd
        for fp in files:
            try:
                df = pd.read_excel(fp) if fp.lower().endswith(("xlsx", "xls")) else pd.read_csv(fp)
            except Exception:
                continue
            col = next((c for c in df.columns if c.lower() in ("current url", "url")), None)
            if col:
                urls.update(str(u) for u in df[col].dropna())
    # 2) also include anything already in data.json
    dj = os.path.join(HERE, "data.json")
    if os.path.exists(dj):
        try:
            for r in json.load(open(dj)).get("rows", []):
                if r.get("u"): urls.add(r["u"])
        except Exception:
            pass
    if not urls:
        sys.exit("No exports or data.json found to read URLs from.")
    return sorted(urls)

BAD = {"Uncategorized"} | {f"HTTP {c}" for c in (429, 403, 500, 502, 503)} | {"error"}

def main():
    from concurrent.futures import ThreadPoolExecutor, as_completed
    sample = int(sys.argv[sys.argv.index("--sample")+1]) if "--sample" in sys.argv else None
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    urls = unique_urls()
    # fetch anything not yet cached OR previously failed (429/error/uncategorized)
    todo = [u for u in urls if cache.get(u) in (None,) or cache.get(u) in BAD]
    if sample: todo = todo[:sample]
    print(f"{len(urls)} unique URLs; {len(todo)} to (re)fetch; workers={WORKERS}, delay={DELAY}s")
    done = 0
    def worker(u):
        time.sleep(DELAY * random.uniform(0.6, 1.4))
        return u, fetch(u)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(worker, u): u for u in todo}
        for f in as_completed(futs):
            u, cat = f.result(); cache[u] = cat; done += 1
            if sample or done % 50 == 0:
                print(f"  [{done}/{len(todo)}] {cat}  <- {__import__("urllib.parse",fromlist=["urlparse"]).urlparse(u).path if "://" in u else u}")
            if not sample and done % 100 == 0:      # save progress periodically
                json.dump(cache, open(CACHE, "w"), indent=0)
    if sample:
        print("\nSample only — nothing saved."); return
    json.dump(cache, open(CACHE, "w"), indent=0)
    from collections import Counter
    c = Counter(cache.values())
    good = sum(v for k,v in c.items() if k not in BAD)
    print(f"\nWrote url_categories.json ({len(cache)} URLs). Categorized OK: {good}")
    print("Top categories:", dict(c.most_common(12)))
    stuck = sum(v for k,v in c.items() if k in BAD)
    if stuck: print(f"Still failed/uncat: {stuck} — just run the workflow again to retry only those.")

if __name__ == "__main__":
    main()
