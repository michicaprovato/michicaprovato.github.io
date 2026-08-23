#!/usr/bin/env python3
"""Pull Team Good Vibes' fundraising total off the GoFundMe/Classy team page.

The page is server-rendered with a big JS bootstrap object; the team's real
numbers live in a `"team":{"id":<TEAM_ID>...}` blob inside it. We slice that
blob out and read two fields rather than trying to parse the whole thing.

Writes goodvibes/raised.json, and syncs the same numbers into the fallback that
goodvibes/index.html renders before that JSON loads — so the two can't drift.
Exits non-zero without touching either file if the numbers can't be found, so a
GoFundMe markup change fails loudly in CI and the site keeps serving the last
known-good value.

    python3 scripts/fetch-raised.py            # write both files
    python3 scripts/fetch-raised.py --dry-run  # print what it found
"""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

TEAM_ID = "824788"
TEAM_URL = f"https://pro.gofundme.com/team/{TEAM_ID}"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(ROOT, "goodvibes", "raised.json")
PAGE_PATH = os.path.join(ROOT, "goodvibes", "index.html")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-CA,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=45) as res:
        return res.read().decode("utf-8", errors="replace")


def extract(html):
    anchor = f'"team":{{"id":{TEAM_ID}'
    start = html.find(anchor)
    if start == -1:
        raise SystemExit(f"could not find the team blob for id {TEAM_ID} — "
                         "the page markup or the team id may have changed")
    blob = html[start:start + 4000]

    def num(field):
        m = re.search(r'"%s":\s*"?([0-9]+(?:\.[0-9]+)?)"?' % field, blob)
        if not m:
            raise SystemExit(f"found the team blob but not a '{field}' value")
        return float(m.group(1))

    raised = num("total_raised")
    goal = num("goal_raw")

    cur = re.search(r'"currency_code":"([A-Z]{3})"', blob)
    currency = cur.group(1) if cur else "CAD"

    # A zero or negative total means we parsed the wrong thing.
    if raised <= 0 or goal <= 0:
        raise SystemExit(f"implausible values: raised={raised} goal={goal}")

    return {"raised": round(raised, 2), "goal": round(goal, 2),
            "currency": currency}


def money(n):
    """$7,493 — whole dollars, en-CA grouping, matching the page's own format."""
    return "${:,.0f}".format(n)


def sync_page(raised, goal):
    """Rewrite the fallback numbers baked into index.html.

    These are what the page renders for the instant before raised.json loads
    (and permanently, if that fetch ever fails), so they have to track the
    live values. Each pattern must match exactly once — anything else means
    the markup moved and a blind rewrite would corrupt it.
    """
    html = open(PAGE_PATH).read()
    pct = max(2, min(100, raised / goal * 100))
    over = raised >= goal
    note = ("raised so far this year &middot; past our %s goal" % money(goal)
            if over else
            "raised so far this year &middot; goal %s" % money(goal))

    edits = [
        (r'(<span id="raised-label"[^>]*>)[^<]*(</span>)',
         r"\g<1>%s\g<2>" % money(raised)),
        (r'(<span id="goal-note"[^>]*>)[^<]*(</span>)',
         r"\g<1>%s\g<2>" % note),
        (r'(<div id="progress-fill" style="height: 100%; width: )[0-9.]+%',
         r"\g<1>%.4g%%" % pct),
        (r'(var RAISED_THIS_YEAR = )[0-9]+', r"\g<1>%d" % round(raised)),
        (r'(var FUNDRAISING_GOAL = )[0-9]+', r"\g<1>%d" % round(goal)),
    ]
    for pattern, repl in edits:
        html, n = re.subn(pattern, repl, html, count=1)
        if n != 1:
            raise SystemExit(f"index.html: no match for {pattern!r} — the "
                             "markup changed; not rewriting the page")

    open(PAGE_PATH, "w").write(html)


def main():
    dry = "--dry-run" in sys.argv
    data = extract(fetch(TEAM_URL))
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["source"] = TEAM_URL

    rendered = json.dumps(data, indent=2) + "\n"
    if dry:
        sys.stdout.write(rendered)
        return

    with open(OUT_PATH, "w") as f:
        f.write(rendered)
    sync_page(data["raised"], data["goal"])
    print(f"wrote {OUT_PATH} and synced {PAGE_PATH}: "
          f"${data['raised']:,.2f} of ${data['goal']:,.2f} {data['currency']}")


if __name__ == "__main__":
    main()
