#!/usr/bin/env python3
"""
Scrape breadcrumb "primary category" using a REAL browser (Playwright).
=======================================================================
saasworthy.com blocks plain requests (HTTP 403), so this uses headless Chromium
to load each page like a real user, then reads the breadcrumb:
   Home / <Primary Category> / <Product> / <Page>   ->  <Primary Category>
i.e. the FIRST breadcrumb item after "Home".

Writes url_categories.json (URL -> category). Incremental + resumable:
re-running only refetches URLs that are missing or previously failed.

USAGE (locally)
  pip install playwright beautifulsoup4 pandas openpyxl
  python3 -m playwright install chromium
  python3 scrape_pw.py --sample 10     # test 10 URLs, prints results
  python3 scrape_pw.py                  # full run
"""
import os, sys, json, glob, asyncio, random
from urllib.parse import urlparse
from bs4 import BeautifulSoup

HERE  = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "url_categories.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

CONCURRENCY = 4        # simultaneous pages
NAV_TIMEOUT = 30000    # ms per page
RETRIES     = 3
BAD = {"Uncategorized", "error", "blocked", "timeout"} | {f"HTTP {c}" for c in (403,404,429,500,502,503)}

def pick(names):
    """Primary category = first breadcrumb item after 'Home'."""
    names = [n for n in names if n]
    if names and names[0].lower() == "home":
        names = names[1:]
    return names[0] if names else None

def extract_category(html):
    import html as H
    soup = BeautifulSoup(html, "html.parser")
    # 1) schema.org BreadcrumbList
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
                        if nm: names.append(H.unescape(str(nm).strip()))
                    c = pick(names)
                    if c: return c
    # 2) visible breadcrumb trail
    for sel in ['[class*="breadcrumb"]', 'nav[aria-label*="readcrumb"]', 'ol.breadcrumb', 'ul.breadcrumb']:
        el = soup.select_one(sel)
        if el:
            raw = [a.get_text(strip=True) for a in el.find_all(["a", "span", "li"])]
            seen = []
            for n in raw:
                if n and (not seen or seen[-1] != n): seen.append(H.unescape(n))
            c = pick(seen)
            if c: return c
    return "Uncategorized"

def unique_urls():
    urls = set()
    pats = ("*.xlsx","*.xls","*.csv","exports/*.xlsx","exports/*.xls","exports/*.csv")
    files = sum([glob.glob(os.path.join(HERE, p)) for p in pats], [])
    if files:
        import pandas as pd
        for fp in files:
            try: df = pd.read_excel(fp) if fp.lower().endswith(("xlsx","xls")) else pd.read_csv(fp)
            except Exception: continue
            col = next((c for c in df.columns if c.lower() in ("current url","url")), None)
            if col: urls.update(str(u) for u in df[col].dropna())
    dj = os.path.join(HERE, "data.json")
    if os.path.exists(dj):
        try:
            for r in json.load(open(dj)).get("rows", []):
                if r.get("u"): urls.add(r["u"])
        except Exception: pass
    if not urls: sys.exit("No exports or data.json found to read URLs from.")
    return sorted(urls)

async def fetch(context, url):
    for attempt in range(RETRIES):
        page = await context.new_page()
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            await page.wait_for_timeout(800 + random.randint(0, 700))
            html = await page.content()
            title = (await page.title() or "").lower()
            await page.close()
            if "just a moment" in title or "attention required" in title:
                await asyncio.sleep(5 * (attempt + 1)); continue        # cloudflare challenge
            cat = extract_category(html)
            if cat not in BAD:
                return cat
            if resp and resp.status in (403, 429, 503):
                await asyncio.sleep(5 * (attempt + 1)); continue
            return cat
        except Exception:
            try: await page.close()
            except Exception: pass
            await asyncio.sleep(3 * (attempt + 1))
    return "blocked"

async def main():
    from playwright.async_api import async_playwright
    sample = int(sys.argv[sys.argv.index("--sample")+1]) if "--sample" in sys.argv else None
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    urls = unique_urls()
    todo = [u for u in urls if cache.get(u) in (None,) or cache.get(u) in BAD]
    if sample: todo = todo[:sample]
    print(f"{len(urls)} unique URLs; {len(todo)} to (re)fetch; concurrency={CONCURRENCY}")
    done = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox","--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(user_agent=UA, viewport={"width":1366,"height":900},
                                             locale="en-US", extra_http_headers={"Accept-Language":"en-US,en;q=0.9"})
        sem = asyncio.Semaphore(CONCURRENCY)
        lock = asyncio.Lock()
        async def worker(u):
            nonlocal done
            async with sem:
                cat = await fetch(context, u)
                async with lock:
                    cache[u] = cat; done += 1
                    if sample or done % 25 == 0:
                        print(f"  [{done}/{len(todo)}] {cat}  <- {urlparse(u).path}")
                    if not sample and done % 100 == 0:
                        json.dump(cache, open(CACHE,"w"), indent=0)
        await asyncio.gather(*(worker(u) for u in todo))
        await browser.close()
    if sample:
        print("\nSample only — nothing saved."); return
    json.dump(cache, open(CACHE,"w"), indent=0)
    from collections import Counter
    c = Counter(cache.values())
    good = sum(v for k,v in c.items() if k not in BAD)
    print(f"\nWrote url_categories.json ({len(cache)} URLs). Categorized OK: {good}")
    print("Top categories:", dict(c.most_common(12)))
    stuck = sum(v for k,v in c.items() if k in BAD)
    if stuck: print(f"Still failed/blocked: {stuck} — run again to retry only those.")

if __name__ == "__main__":
    asyncio.run(main())
