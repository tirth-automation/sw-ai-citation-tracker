# SaaSworthy — AI Overview (SEO/GEO) + Review dashboards

A self-contained clone of the SoftwareSuggest tracker, retargeted to **saasworthy.com**.
No API key needed — you update it by uploading an Ahrefs export; a GitHub Action rebuilds it.

## What's inside
```
index.html               Main dashboard  (AI Overview / SEO-GEO)  -> your live link "/"
build_from_export.py     Turns an Ahrefs export into data.json (domain-agnostic)
scrape_categories.py     Reads each page's breadcrumb -> url_categories.json (Primary category)
.github/workflows/static.yml            Rebuilds + deploys on every commit/upload
.github/workflows/scrape-categories.yml Manual: fetch breadcrumb categories
exports/                 Drop new saasworthy.com Ahrefs exports here
snapshots/               Auto-created; powers the 7-day citation check
```

## One-time setup (~10 min)
1. Create a NEW GitHub repo (e.g. `sw-ai`).
2. Upload everything here to the repo root (keep the folder structure).
3. Settings -> Pages -> Source "GitHub Actions" (or "Deploy from a branch" -> main/root).
   Your link appears, e.g. `https://<user>.github.io/sw-ai/`.
4. Add your first saasworthy.com Ahrefs export (Site Explorer -> AI-Overview organic keywords -> Export)
   into `exports/` (or repo root). The deploy builds `data.json` from it automatically.

## Fill in Primary categories (breadcrumb scrape)
1. Actions -> "Scrape URL categories" -> Run workflow.  (slow but rate-limit safe; resumes if re-run)
2. When done, re-run "Deploy static content to Pages".  Categories now show on both dashboards.

## Daily/whenever update
Upload a fresh export to `exports/` -> commit -> the deploy rebuilds automatically.
Run "Scrape URL categories" again only when NEW URLs appear (it skips ones already done).

## Notes
- The Ahrefs export columns are identical across sites, so the build script works as-is.
- The URL-*type* tag (Blog/Comparison/etc.) uses generic rules and may show "Other" for some
  saasworthy URL patterns; tell me the patterns and I'll tune them. The **Primary category**
  (from the page breadcrumb) is what matters and works regardless of URL structure.
