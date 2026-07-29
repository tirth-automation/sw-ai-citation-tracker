#!/usr/bin/env python3
"""
Build the dashboard data from an Ahrefs export — NO API KEY NEEDED.
===================================================================
Reads the newest Ahrefs "Organic keywords" export (.xlsx or .csv) from the
`exports/` folder, rebuilds data.json (which ai_overview_dashboard.html reads),
saves a dated snapshot, and computes the 7-day citation check.

DAILY ROUTINE
  1. In Ahrefs Site Explorer, open your AI-Overview organic-keywords view.
  2. Click Export (XLSX or CSV).
  3. Drop the file into the `exports/` folder (any filename).
  4. Run:  python3 build_from_export.py
     -> updates data.json; the dashboard shows the new data.

The export must contain these columns (default Ahrefs export already does):
  Keyword, Volume, Current position, Current position kind, SERP features,
  Organic traffic, KD, Location, Country, Current URL, Updated,
  and the intent flags (Branded, Informational, Commercial, Transactional, ...).
"""
import os, sys, json, glob, datetime
import pandas as pd

HERE   = os.path.dirname(os.path.abspath(__file__))
EXPORTS= os.path.join(HERE, "exports")
SNAPDIR= os.path.join(HERE, "snapshots")
PRE    = "https://www.saasworthy.com"  # only used as a display hint; path parsing is domain-agnostic
CAT_SUFFIX = ("-software","-tools","-system","-systems","-solutions","-app","-apps",
              "-platform","-platforms","-services","-suite")

def category(u):
    """Derive the primary page-type category from a URL path (saasworthy + generic)."""
    from urllib.parse import urlparse
    p = urlparse(u).path if isinstance(u, str) and "://" in u else (u or "")
    s = [x for x in p.strip("/").split("/") if x]
    if not s: return "Homepage"
    first = s[0]; second = s[1] if len(s) > 1 else ""; last = s[-1]
    # --- saasworthy.com patterns ---
    if first == "list": return "Category page"                 # /list/contest-software
    if first == "product-alternative": return "Alternatives"   # /product-alternative/167/vyper
    if first == "product":
        if last == "pricing":       return "Pricing page"       # /product/untap-compete/pricing
        if last == "reviews":       return "Reviews"            # /product/x/reviews
        if last == "alternatives":  return "Alternatives"
        if last == "features":      return "Vendor sub-page"
        return "Vendor / product"                              # /product/vyper
    if first == "compare" or first == "product-comparison": return "Comparison"
    if first == "blog": return "Blog"
    # --- generic / SoftwareSuggest fallbacks ---
    if second == "alternatives": return "Alternatives"
    if second == "reviews": return "Reviews"
    if second in ("pricing", "features", "mobile-app"): return "Vendor sub-page"
    if any(first.endswith(x) for x in CAT_SUFFIX): return "Category page"
    if first == "services": return "Services"
    if len(s) == 1: return "Vendor / product"
    return "Other"

def newest_export():
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        return sys.argv[1]
    files = []
    for ext in ("*.xlsx","*.xls","*.csv"):
        files += glob.glob(os.path.join(EXPORTS, ext))
    if not files:
        sys.exit(f"No export found. Put an Ahrefs .xlsx/.csv into: {EXPORTS}")
    return max(files, key=os.path.getmtime)

def load(path):
    if path.lower().endswith(".csv"):
        try: return pd.read_csv(path)
        except UnicodeDecodeError: return pd.read_csv(path, encoding="utf-16", sep="\t")
    return pd.read_excel(path)

def col(df, *names):
    low = {c.lower().strip(): c for c in df.columns}
    for n in names:
        if n.lower() in low: return low[n.lower()]
    return None

def intent(row, df):
    order = [("Transactional","Transactional"),("Commercial","Commercial"),
             ("Branded","Branded"),("Navigational","Navigational"),
             ("Local","Local"),("Informational","Informational")]
    for label,name in order:
        c = col(df, label)
        if c is not None and bool(row.get(c)): return name
    return "Other"

def load_pmap():
    p = os.path.join(HERE, "url_categories.json")
    if os.path.exists(p):
        try: return json.load(open(p))
        except Exception: return {}
    return {}

def build(df):
    PMAP = load_pmap()
    C = {k: col(df, *v) for k,v in {
        "kw":["Keyword"], "vol":["Volume"], "pos":["Current position","Position"],
        "kind":["Current position kind"], "serp":["SERP features"],
        "traf":["Organic traffic","Traffic"], "loc":["Location"], "cc":["Country"],
        "url":["Current URL","URL"], "upd":["Updated","Last updated"],
    }.items()}
    rows=[]
    today = datetime.date.today().isoformat()
    for _,r in df.iterrows():
        u = str(r[C["url"]]) if C["url"] and pd.notna(r[C["url"]]) else ""
        d = today
        if C["upd"] and pd.notna(r[C["upd"]]):
            d = str(pd.to_datetime(r[C["upd"]]).date())
        pcat = PMAP.get(u) or PMAP.get(u.rstrip("/")) or PMAP.get(u + "/") or "Uncategorized"
        rows.append({
            "k": str(r[C["kw"]]) if C["kw"] else "",
            "v": int(r[C["vol"]]) if C["vol"] and pd.notna(r[C["vol"]]) else 0,
            "p": int(r[C["pos"]]) if C["pos"] and pd.notna(r[C["pos"]]) else None,
            "a": 1 if (C["kind"] and str(r[C["kind"]])=="AI Overview") else 0,
            "t": int(r[C["traf"]]) if C["traf"] and pd.notna(r[C["traf"]]) else 0,
            "in": intent(r, df),
            "loc": str(r[C["loc"]]) if C["loc"] and pd.notna(r[C["loc"]]) else "Unknown",
            "cc": (str(r[C["cc"]]).upper() if C["cc"] and pd.notna(r[C["cc"]]) else ""),
            "d": d, "u": u, "pa": (__import__("urllib.parse", fromlist=["urlparse"]).urlparse(u).path or "/") if "://" in u else (u or "/"),
            "cat": category(u), "pcat": pcat,
        })
    return rows

def seven_day(rows):
    target = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    prev = {}
    if os.path.isdir(SNAPDIR):
        snaps = sorted(f[:-5] for f in os.listdir(SNAPDIR) if f.endswith(".json"))
        pick = max((s for s in snaps if s <= target), default=(snaps[0] if snaps else None))
        if pick:
            for x in json.load(open(os.path.join(SNAPDIR, pick+".json"))): prev[x["k"]] = x
    for r in rows:
        old = prev.get(r["k"])
        if not prev: r["c7"]=None
        elif old is None: r["c7"]="new"
        elif r["a"] and old.get("a"): r["c7"]="held"
        elif r["a"] and not old.get("a"): r["c7"]="gained"
        elif not r["a"] and old.get("a"): r["c7"]="lost"
        else: r["c7"]=None
    return rows

def meta(rows):
    from collections import Counter
    locs=Counter(r["loc"] for r in rows); tl=Counter(r["d"] for r in rows)
    cats=Counter(r["cat"] for r in rows)
    pcats=Counter(r.get("pcat","Uncategorized") for r in rows)
    return {"target":"www.saasworthy.com","is_sample":False,
        "export_date":datetime.date.today().isoformat(),"date":datetime.date.today().isoformat(),
        "max_date":max(tl) if tl else "","total":len(rows),
        "sv":sum(r["v"] for r in rows),"cited":sum(r["a"] for r in rows),
        "pos1":sum(1 for r in rows if r["p"]==1),"pages":len({r["u"] for r in rows if r["u"]}),
        "gained7":sum(1 for r in rows if r.get("c7")=="gained"),
        "lost7":sum(1 for r in rows if r.get("c7")=="lost"),
        "locs":[{"n":n,"c":c} for n,c in locs.most_common()],
        "cats":[{"n":n,"c":c} for n,c in cats.most_common()],
        "pcats":[{"n":n,"c":c} for n,c in pcats.most_common()],
        "timeline":[{"d":d,"c":tl[d]} for d in sorted(tl)]}

def main():
    os.makedirs(SNAPDIR, exist_ok=True); os.makedirs(EXPORTS, exist_ok=True)
    path = newest_export()
    print("Reading:", os.path.basename(path))
    rows = build(load(path))
    print(f"Parsed {len(rows)} prompts.")
    today = datetime.date.today().isoformat()
    json.dump([{"k":r["k"],"a":r["a"],"p":r["p"]} for r in rows],
              open(os.path.join(SNAPDIR, f"{today}.json"),"w"))
    rows = seven_day(rows)
    m = meta(rows)
    json.dump({"meta":m,"rows":rows}, open(os.path.join(HERE,"data.json"),"w"))
    print(f"Wrote data.json — {m['total']} prompts, {m['cited']} cited "
          f"({round(m['cited']/max(m['total'],1)*100)}%), 7-day: +{m['gained7']} / -{m['lost7']}.")

if __name__ == "__main__":
    main()
