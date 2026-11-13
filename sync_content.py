#!/usr/bin/env python3
"""
Viral Content Sync — Supabase edition
--------------------------------------
Scrapes one tracker's competitors via Apify (profiles for follower counts,
then recent posts), keeps the standout posts, and UPSERTS into the Supabase
`posts` table.

A post is kept when it clears a small noise floor AND passes ANY of three
tests (OR, not AND -- the old AND rule starved small and large accounts
alike):
  1. engagement rate  >= MIN_ER
  2. comments         >= MIN_COMMENTS
  3. engagements      >= OUTLIER_X x that account's OWN median engagements
     (median taken over the posts scraped this run -- a real baseline, so a
     5k-follower account is judged against itself, not against a 300k one)
On top of that, every account always contributes its TOP_N_PER_COMP best
posts, so a quiet week still fills the dashboard instead of showing zero.

Widening the filter costs NOTHING extra on Apify: the scrape already pulls
every post, the filter only decides what gets stored.

Upsert notes: existing posts get their metrics/video URL refreshed (fresh
CDN links let previously skipped videos transcribe); status / transcript /
ai_breakdown are never in the payload, so worked rows are never clobbered.
engagement_rate and viral_score are generated columns — never written.

Env (required): TRACKER ("IG", "FB" or "AI"), APIFY_TOKEN, SUPABASE_URL,
                SUPABASE_SERVICE_ROLE_KEY

Facebook (TRACKER=FB): competitors are public Facebook *pages*. In the
competitors table put the page slug (facebook.com/<slug>) or the full page URL.
Uses apify/facebook-pages-scraper (followers) + apify/facebook-posts-scraper
(posts). Facebook engagement rates are far lower than Instagram's, so the
default MIN_ER / MIN_COMMENTS / MIN_ENGAGE are lower when TRACKER=FB.
Env (tuning, all optional -- set as GitHub Actions *Variables*):
     MIN_ER (0.02)  MIN_COMMENTS (15)  MIN_ENGAGE (20)  OUTLIER_X (1.5)
     TOP_N_PER_COMP (3)  MAX_PER_COMP (15)  DAYS_BACK (60)
     RESULTS_LIMIT (50)  MAX_ROWS (2500)
"""

import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

TRACKER = (os.environ.get("TRACKER") or "AI").strip().upper()
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")

POLL_INTERVAL = 30
POLL_TIMEOUT = 900
PROTECTED = ("拍摄中", "已处理")


def _envf(name, default):
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return float(default)


def _envi(name, default):
    try:
        return int(float(os.environ.get(name) or default))
    except ValueError:
        return int(default)


# --- tuning knobs (GitHub Actions Variables; defaults are the loose set) ---
IS_FB = TRACKER == "FB"
# ONLY_NEW=1: scrape only accounts that have no posts in the database yet (the
# ones just added from the dashboard). Everything already tracked is left alone,
# so no Apify money is spent re-fetching it. The weekly run leaves this unset.
ONLY_NEW = (os.environ.get("ONLY_NEW") or "").strip().lower() in ("1", "true", "yes")
# Facebook pages get far less engagement per follower than Instagram, so the
# FB defaults are lower. Same variable names; override in Actions Variables.
MIN_ER         = _envf("MIN_ER", 0.005 if IS_FB else 0.02)    # IG 2% / FB 0.5%
MIN_COMMENTS   = _envi("MIN_COMMENTS", 5 if IS_FB else 15)    # absolute comment count
MIN_ENGAGE     = _envi("MIN_ENGAGE", 10 if IS_FB else 20)     # noise floor: likes+comments
OUTLIER_X      = _envf("OUTLIER_X", 1.5)      # x the account's own median
TOP_N_PER_COMP = _envi("TOP_N_PER_COMP", 3)   # always keep each account's best N
MAX_PER_COMP   = _envi("MAX_PER_COMP", 15)    # cap per account, so one big
                                              # account cannot flood the board
DAYS_BACK      = _envi("DAYS_BACK", 60)       # lookback window (free volume)
RESULTS_LIMIT  = _envi("RESULTS_LIMIT", 50)   # posts scraped per NEW account (costs $)
REFRESH_DAYS   = _envi("REFRESH_DAYS", 21)    # accounts we already have: only look back this far
REFRESH_LIMIT  = _envi("REFRESH_LIMIT", 25)   # ...and scrape at most this many posts (costs $)
MAX_ROWS       = _envi("MAX_ROWS", 2500)      # dashboard payload cap


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _request(url, method="GET", data=None, headers=None, timeout=60):
    hdrs = headers or {}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return raw
    except urllib.error.HTTPError as exc:
        print(f"  HTTP {exc.code} for {method} {url[:100]}")
        print(f"  Response: {exc.read().decode('utf-8', errors='replace')[:400]}")
        raise


def sb(path, method="GET", data=None, prefer=None):
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key}  # new-style keys are not JWTs: apikey header only
    if prefer:
        headers["Prefer"] = prefer
    return _request(f"{SUPABASE_URL}/rest/v1/{path}", method, data, headers, 60)


# ---------------------------------------------------------------------------
# Competitors (self-service list in Supabase)
# ---------------------------------------------------------------------------


FB_NON_PAGE = ("posts", "photo", "photos", "videos", "reel", "reels", "watch",
               "groups", "events", "share", "permalink.php", "story.php",
               "profile.php", "hashtag")


def fb_slug(value):
    """'facebook.com/Foo/posts/1', 'https://www.facebook.com/Foo/', '@Foo'
    -> 'foo'. Returns '' for links that are not a page (post, group, profile.php)."""
    n = (value or "").strip()
    if "facebook.com" in n or "fb.com" in n:
        if "//" not in n:
            n = "https://" + n
        parts = [p for p in urllib.parse.urlparse(n).path.split("/") if p]
        if not parts or parts[0].lower() in FB_NON_PAGE:
            return ""
        n = parts[0]
    return n.lstrip("@").strip().lower()


COMP_INFO = {}   # lower-cased account name -> {"id":..., "notes":...}, filled by fetch_competitors


def fetch_competitors():
    rows = sb(f"competitors?select=id,username,notes&tracker=eq.{TRACKER}&active=is.true")
    names = []
    for r in rows:
        n = (r.get("username") or "").strip()
        COMP_INFO[(fb_slug(n) if IS_FB else n.lstrip("@").strip()).lower()] = {
            "id": r.get("id"), "notes": r.get("notes") or ""}
        if IS_FB:
            slug = fb_slug(n)
            if not slug:
                print(f"  WARNING: skipping non-page Facebook link: {n[:60]}")
                continue
            names.append(slug)
            continue
        if "instagram.com" in n:
            parts = [p for p in urllib.parse.urlparse(n).path.split("/") if p]
            if not parts or parts[0] in ("p", "reel", "reels", "stories", "tv"):
                print(f"  WARNING: skipping non-profile link: {n[:60]}")
                continue
            n = parts[0]
        n = n.lstrip("@").strip()
        if n:
            names.append(n)
    return names


def suggest_competitors(profile_items):
    """Rolling shortlist: replace last week's un-adopted suggestions with
    this week's most frequent unseen related profiles."""
    existing = {(r.get("username") or "").lower().lstrip("@")
                for r in sb("competitors?select=username")}
    counts = {}
    for prof in profile_items:
        for rp in (prof.get("relatedProfiles") or []):
            u = (rp.get("username") or "").strip().lower()
            if u and u not in existing:
                counts[u] = counts.get(u, 0) + 1
    top = sorted(counts.items(), key=lambda x: -x[1])[:8]
    if not top:
        print("[Suggest] no new related profiles this run")
        return
    # clear old un-adopted suggestions for this tracker
    pat = urllib.parse.quote("系统推荐*")
    sb(f"competitors?tracker=eq.{TRACKER}&active=is.false&notes=like.{pat}",
       method="DELETE", prefer="return=minimal")
    today = datetime.now(timezone.utc).date().isoformat()
    sb("competitors", method="POST", prefer="return=minimal", data=[
        {"username": u, "tracker": TRACKER, "active": False,
         "notes": f"系统推荐 {today}(相关度 {n})— 觉得好就把 active 打勾"}
        for u, n in top
    ])
    print(f"[Suggest] refreshed shortlist: {', '.join(u for u, _ in top)}")


# ---------------------------------------------------------------------------
# Apify
# ---------------------------------------------------------------------------


def run_actor(token, actor_id, actor_input, label):
    print(f"[{label}] {actor_id}...")
    result = _request(f"https://api.apify.com/v2/acts/{actor_id}/runs?token={token}",
                      "POST", actor_input, timeout=120)
    run_id = result["data"]["id"]
    print(f"  run {run_id}")
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        st = _request(f"https://api.apify.com/v2/actor-runs/{run_id}?token={token}",
                      timeout=30)["data"]
        print(f"  {st['status']}")
        if st["status"] == "SUCCEEDED":
            items = _request(
                f"https://api.apify.com/v2/datasets/{st['defaultDatasetId']}/items"
                f"?token={token}&clean=true", timeout=120)
            return items if isinstance(items, list) else []
        if st["status"] in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"Apify run ended: {st['status']}")
    # abort so a run nobody will fetch stops billing
    try:
        _request(f"https://api.apify.com/v2/actor-runs/{run_id}/abort?token={token}",
                 "POST", timeout=30)
        print(f"  aborted {run_id} to stop billing")
    except Exception as exc:
        print(f"  WARNING: could not abort {run_id}: {exc}")
    raise TimeoutError(f"run {run_id} exceeded {POLL_TIMEOUT}s — fewer competitors "
                       f"or a higher POLL_TIMEOUT needed")


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------


def parse_date(v):
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc).date().isoformat()
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
    return None


def post_type(p):
    m = {"Image": "Image", "Video": "Video", "Sidecar": "Carousel", "Reel": "Reel"}
    return m.get((p.get("type") or "").strip(),
                 "Video" if p.get("isVideo") else "Image")


def parse_ig(p, followers_map, today):
    """One Instagram post -> (account, row). Returns (None, None) if unusable,
    (account, None) when the follower count is missing."""
    if p.get("error") or not p.get("shortCode"):
        return None, None
    u = (p.get("ownerUsername") or (p.get("owner") or {}).get("username") or "")
    u = u.lower().strip()
    fol = followers_map.get(u, 0)
    if not fol:
        return u, None
    likes = int(p.get("likesCount") or p.get("likes") or 0)
    comments = int(p.get("commentsCount") or p.get("comments") or 0)
    pt = post_type(p)
    tags = p.get("hashtags") or []
    return u, {
        "post_id": p["shortCode"],
        "tracker": TRACKER,
        "competitor": u,
        "caption": (p.get("caption") or "")[:5000],
        "post_type": pt,
        "likes": likes,
        "comments": comments,
        "followers": fol,
        "post_date": parse_date(p.get("timestamp")),
        "post_url": f"https://www.instagram.com/p/{p['shortCode']}/",
        "thumbnail_url": p.get("displayUrl") or p.get("imageUrl") or None,
        "video_url": p.get("videoUrl") or None,
        "hashtags": ", ".join(tags) if isinstance(tags, list) else str(tags),
        "is_video": bool(p.get("isVideo") or pt in ("Video", "Reel")),
        "last_synced": today,
    }


def parse_fb(p, followers_map, today):
    """One Facebook post (apify/facebook-posts-scraper) -> (page, row).

    Facebook's `likes` is the total reaction count, so it maps onto the same
    likes column the dashboard already uses. Shares and views are not stored
    (no columns), so they do not affect the score. post_id gets an `fb_` prefix
    so it can never collide with an Instagram shortcode. video_url stays empty:
    Facebook video links expire and are not reliably downloadable, so Whisper
    transcription skips Facebook posts."""
    if p.get("error") or not p.get("postId"):
        return None, None
    u = (fb_slug(p.get("inputUrl") or "") or fb_slug(p.get("facebookUrl") or "")
         or (p.get("pageName") or "").lower().strip())
    if not u:
        return None, None
    fol = followers_map.get(u, 0)
    if not fol:
        return u, None
    likes = int(p.get("likes") or 0)
    comments = int(p.get("comments") or 0)
    media = p.get("media") or []
    first = media[0] if media and isinstance(media[0], dict) else {}
    url = p.get("url") or p.get("topLevelUrl") or ""
    is_video = bool(p.get("viewsCount")
                    or str(first.get("__typename") or "").lower() == "video"
                    or any(k in url for k in ("/reel/", "/videos/", "/watch")))
    if is_video:
        pt = "Reel" if "/reel/" in url else "Video"
    elif len(media) > 1:
        pt = "Carousel"
    else:
        pt = "Image"
    text = p.get("text") or ""
    tags = [t.lstrip("#") for t in re.findall(r"#\w+", text)]
    thumb = first.get("thumbnail") or (first.get("photo_image") or {}).get("uri")
    return u, {
        "post_id": "fb_" + str(p["postId"]),
        "tracker": TRACKER,
        "competitor": u,
        "caption": text[:5000],
        "post_type": pt,
        "likes": likes,
        "comments": comments,
        "followers": fol,
        "post_date": parse_date(p.get("time") if p.get("time") else p.get("timestamp")),
        "post_url": url or None,
        "thumbnail_url": thumb or None,
        "video_url": None,
        "hashtags": ", ".join(tags),
        "is_video": is_video,
        "last_synced": today,
    }


def to_rows(posts, followers_map, today):
    """Group the scrape by account, judge each account against ITSELF, and
    guarantee every account contributes its best few posts."""
    parse = parse_fb if IS_FB else parse_ig
    by_comp, nofol, broken = {}, 0, 0
    for p in posts:
        u, row = parse(p, followers_map, today)
        if u is None:
            broken += 1
            continue
        if row is None:
            nofol += 1
            continue
        fol, likes, comments = row["followers"], row["likes"], row["comments"]
        by_comp.setdefault(u, []).append({
            "row": row,
            "eng": likes + comments,
            "er": (likes + comments) / fol,
            "comments": comments,
            # same weighting the dashboard sorts by, so "top N" means the same thing
            "score": (likes + comments * 3) / fol * 100,
        })

    rows, below_total, rescued_total = [], 0, 0
    print(f"  {'账号':<24}{'抓到':>5}{'入选':>5}{'补位':>5}  基准/中位互动")
    for u in sorted(by_comp):
        recs = by_comp[u]
        engs = [r["eng"] for r in recs]
        med = statistics.median(engs) if len(engs) >= 3 else 0
        keep_ids, kept = set(), []
        for r in recs:
            if r["eng"] < MIN_ENGAGE:
                continue
            if (r["er"] >= MIN_ER
                    or r["comments"] >= MIN_COMMENTS
                    or (med > 0 and r["eng"] >= OUTLIER_X * med)):
                keep_ids.add(r["row"]["post_id"])
                kept.append(r)
        passed = len(kept)
        # safety net: a quiet account still contributes its best posts
        rescued = 0
        if passed < TOP_N_PER_COMP:
            for r in sorted(recs, key=lambda r: -r["score"]):
                if r["row"]["post_id"] in keep_ids:
                    continue
                keep_ids.add(r["row"]["post_id"])
                kept.append(r)
                rescued += 1
                if len(kept) >= TOP_N_PER_COMP:
                    break
        # cap: keep the best MAX_PER_COMP so one large account cannot flood
        capped = 0
        if len(kept) > MAX_PER_COMP:
            kept.sort(key=lambda r: -r["score"])
            capped = len(kept) - MAX_PER_COMP
            kept = kept[:MAX_PER_COMP]
        below_total += len(recs) - passed
        rescued_total += rescued
        rows.extend(r["row"] for r in kept)
        note = f" · 超额截掉 {capped}" if capped else ""
        print(f"  @{u:<23}{len(recs):>5}{len(kept):>5}{rescued:>5}  "
              f"中位 {int(med)} 互动 · {recs[0]['row']['followers']:,} 粉{note}")

    print(f"  ── 合计 {len(rows)} 条入库 "
          f"({len(rows) - rescued_total} 达标 + {rescued_total} 补位) | "
          f"{below_total} 条未达标 | {nofol} 条缺粉丝数 | {broken} 条抓取失败")
    if len(rows) < 20:
        print("  提示: 内容偏少。到仓库 Settings → Variables 调松阈值，例如")
        print("        MIN_ER=0.01  MIN_COMMENTS=8  OUTLIER_X=1.2  TOP_N_PER_COMP=5")
        print("        想要每个账号更多条 → 调大 MAX_PER_COMP")
        print("        或在 Supabase 的 competitors 表多加几个竞对账号。")
    return rows


# ---------------------------------------------------------------------------
# Cleanup (dashboard weight, not Supabase limits — free tier holds 500MB)
# ---------------------------------------------------------------------------


def cleanup():
    rows = sb("posts?select=post_id,status,last_synced&order=last_synced.asc.nullsfirst")
    if len(rows) <= MAX_ROWS:
        print(f"[Cleanup] {len(rows)} rows <= {MAX_ROWS}, nothing removed")
        return
    overflow = len(rows) - MAX_ROWS
    victims = [r["post_id"] for r in rows if r.get("status") not in PROTECTED][:overflow]
    if not victims:
        print(f"[Cleanup] WARNING: {overflow} over cap but all rows carry work")
        return
    for i in range(0, len(victims), 100):
        chunk = ",".join(victims[i:i+100])  # IG shortcodes are URL-safe
        sb(f"posts?post_id=in.({chunk})",
           method="DELETE", prefer="return=minimal")
    print(f"[Cleanup] removed {len(victims)} oldest unworked rows")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def has_posts(name):
    """True when this account already has at least one post stored."""
    rows = sb(f"posts?select=post_id&tracker=eq.{TRACKER}"
              f"&competitor=eq.{urllib.parse.quote(name.lower())}&limit=1")
    return bool(rows)


FAIL_NOTE = "抓取失败"


def report_results(names, followers, rows, today):
    """Write what happened to each account into competitors.notes, so the
    dashboard's 管理竞对 list shows it (typo / private page / no recent posts)
    instead of the account silently producing nothing."""
    counts = {}
    for r in rows:
        counts[r["competitor"]] = counts.get(r["competitor"], 0) + 1
    for n in names:
        key = n.lower()
        info = COMP_INFO.get(key)
        if not info or info.get("id") is None:
            continue
        if not followers.get(key):
            note = f"{FAIL_NOTE} {today}:找不到这个账号/页面(名字拼错,或不是公开主页)"
        elif counts.get(key):
            note = f"上次抓取 {today}:{counts[key]} 条"
        else:
            note = f"上次抓取 {today}:最近没有可显示的帖子"
        if note == info.get("notes"):
            continue
        try:
            sb(f"competitors?id=eq.{info['id']}", method="PATCH",
               data={"notes": note}, prefer="return=minimal")
        except Exception as exc:
            print(f"  (could not save note for {n}: {exc})")


def scrape_posts(token, group, limit, days):
    """One Apify posts run for a group of accounts with its own window/limit."""
    if not group:
        return []
    if IS_FB:
        inp = {"startUrls": [{"url": f"https://www.facebook.com/{n}"} for n in group],
               "resultsLimit": limit, "onlyPostsNewerThan": f"{days} days"}
        return run_actor(token, "apify~facebook-posts-scraper", inp, "Step 2 posts")
    inp = {"username": group, "resultsLimit": limit, "onlyPostsNewerThan": f"{days} days"}
    return run_actor(token, "apify~instagram-post-scraper", inp, "Step 2 posts")


def main():
    token = (os.environ.get("APIFY_TOKEN") or "").strip()
    if not token or not SUPABASE_URL or not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        print("ERROR: APIFY_TOKEN / SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY required")
        sys.exit(1)

    names = fetch_competitors()
    if not names:
        print(f"No active {TRACKER} competitors in Supabase — nothing to do.")
        return
    # "new" = no posts stored yet. New accounts get the full window (DAYS_BACK /
    # RESULTS_LIMIT); accounts we already have only need a short refresh
    # (REFRESH_DAYS / REFRESH_LIMIT) to catch new posts and update the numbers.
    fresh = [n for n in names if not has_posts(n)]
    if ONLY_NEW:
        # accounts already flagged as failed are not retried on every add; pausing
        # and re-adding them from the dashboard clears the flag
        skipped = [n for n in fresh
                   if (COMP_INFO.get(n.lower()) or {}).get("notes", "").startswith(FAIL_NOTE)]
        fresh = [n for n in fresh if n not in skipped]
        print(f"[{TRACKER}] only-new mode: {len(fresh)} new of {len(names)} active"
              + (f" ({', '.join(fresh)})" if fresh else "")
              + (f" | skipping {len(skipped)} flagged as failed" if skipped else ""))
        if not fresh:
            print("Nothing new to scrape — no Apify run started.")
            return
        names = fresh
    existing = [n for n in names if n not in fresh]
    print(f"[{TRACKER}] {len(names)} competitors: {', '.join(names[:8])}"
          + (" ..." if len(names) > 8 else ""))
    print(f"  filter: ER>={MIN_ER:.1%} OR comments>={MIN_COMMENTS} OR "
          f"engagements>={OUTLIER_X}x own median | floor {MIN_ENGAGE} | "
          f"keep {TOP_N_PER_COMP}-{MAX_PER_COMP} per account")

    if IS_FB:
        page_urls = [{"url": f"https://www.facebook.com/{n}"} for n in names]
        profiles = run_actor(token, "apify~facebook-pages-scraper",
                             {"startUrls": page_urls}, "Step 1 pages")
        followers = {}
        for pr in profiles:
            c = pr.get("followers") or pr.get("likes") or 0   # followers, else page likes
            if not c:
                continue
            for key in (fb_slug(pr.get("facebookUrl") or ""), fb_slug(pr.get("pageUrl") or ""),
                        fb_slug(pr.get("inputUrl") or ""), (pr.get("pageName") or "").lower().strip()):
                if key:
                    followers[key] = int(c)
        print(f"  followers for {sum(1 for n in names if n in followers)}/{len(names)}")
    else:
        profiles = run_actor(token, "apify~instagram-profile-scraper",
                             {"usernames": names}, "Step 1 profiles")
        followers = {}
        for pr in profiles:
            u = (pr.get("username") or "").lower().strip()
            c = pr.get("followersCount") or pr.get("followers") or 0
            if u and c:
                followers[u] = int(c)
        print(f"  followers for {len(followers)}/{len(names)}")

        try:
            if ONLY_NEW:
                raise RuntimeError("only-new mode: keeping the existing shortlist")
            suggest_competitors(profiles)
        except Exception as exc:
            print(f"[Suggest] skipped ({exc})")

    posts = (scrape_posts(token, fresh, RESULTS_LIMIT, DAYS_BACK)
             + scrape_posts(token, existing, REFRESH_LIMIT, REFRESH_DAYS))
    print(f"  scraped {len(posts)} posts: {len(fresh)} new account(s) "
          f"(last {DAYS_BACK} days, <= {RESULTS_LIMIT}), {len(existing)} existing "
          f"(last {REFRESH_DAYS} days, <= {REFRESH_LIMIT})")

    today = datetime.now(timezone.utc).date().isoformat()
    rows = to_rows(posts, followers, today)
    try:
        report_results(names, followers, rows, today)
    except Exception as exc:
        print(f"[Notes] skipped ({exc})")
    if rows:
        for i in range(0, len(rows), 100):
            sb("posts?on_conflict=post_id", method="POST", data=rows[i:i+100],
               prefer="resolution=merge-duplicates,return=minimal")
        print(f"[Upsert] {len(rows)} rows written")

        # An IG 403 usually means the CDN signature expired, not that the video
        # is gone. This sync just refreshed those URLs — clear the fail marks so
        # transcription gets another shot with the fresh links.
        mark = urllib.parse.quote("(转录失败)")
        sb(f"posts?transcript=eq.{mark}&last_synced=eq.{today}",
           method="PATCH", data={"transcript": None}, prefer="return=minimal")
        print("[Upsert] reopened previously-failed transcripts with fresh URLs")
    else:
        print("[Upsert] nothing passed the filter — check the per-account table "
              "above, then loosen the Variables or add more competitors")

    try:
        cleanup()
    except Exception as exc:
        print(f"[Cleanup] skipped ({exc})")

    print("Done.")


if __name__ == "__main__":
    main()
