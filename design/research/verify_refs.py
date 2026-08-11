#!/usr/bin/env python3
"""Verify a candidate reference list against Crossref (DOIs) and DataCite (arXiv).

Nothing is accepted on my memory: every entry must come back from an API with
title, full author list, year and venue. Prints a review table + writes JSON.

Usage: verify_refs.py candidates.json out.json
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from difflib import SequenceMatcher

UA = "YazSes-reference-audit/1.0 (mailto:mohsen.seyedkazemi@gmail.com)"


def get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "")


def norm(s):
    return " ".join("".join(c.lower() for c in strip_tags(s) if c.isalnum() or c == " ").split())


def score(a, b):
    return round(SequenceMatcher(None, norm(a), norm(b)).ratio(), 3)


def full_title(m):
    """ACM DL splits 'Put-that-there: Voice and gesture...' into title + subtitle."""
    t = (m.get("title") or [""])[0]
    sub = (m.get("subtitle") or [""])
    sub = sub[0] if sub else ""
    if sub and norm(sub) not in norm(t):
        t = f"{t}: {sub}"
    return " ".join(strip_tags(t).split())


def from_crossref(m):
    return {
        "source": "crossref",
        "title": full_title(m),
        "authors": [
            " ".join(x for x in [a.get("given"), a.get("family")] if x) or a.get("name", "")
            for a in m.get("author", [])
        ],
        "year": (m.get("issued", {}).get("date-parts") or [[None]])[0][0],
        "venue": (m.get("container-title") or m.get("event", {}).get("name") or [""])[0]
        if isinstance(m.get("container-title") or [""], list)
        else "",
        "event": (m.get("event") or {}).get("name", ""),
        "publisher": m.get("publisher", ""),
        "doi": m.get("DOI", ""),
        "type": m.get("type", ""),
    }


def from_datacite(d):
    a = d["data"]["attributes"]
    return {
        "source": "datacite",
        "title": (a.get("titles") or [{}])[0].get("title", ""),
        "authors": [
            c.get("name") if not c.get("givenName") else f"{c.get('givenName')} {c.get('familyName')}"
            for c in a.get("creators", [])
        ],
        "year": a.get("publicationYear"),
        "venue": "arXiv",
        "event": "",
        "publisher": a.get("publisher", ""),
        "doi": a.get("doi", ""),
        "type": a.get("types", {}).get("resourceTypeGeneral", ""),
    }


def resolve(c):
    if c.get("arxiv"):
        url = f"https://api.datacite.org/dois/10.48550/arXiv.{c['arxiv']}"
        return from_datacite(get(url))
    if c.get("doi"):
        try:
            return from_crossref(get(f"https://api.crossref.org/works/{c['doi']}")["message"])
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            print(f"        (DOI {c['doi']} 404 -> falling back to title search)")
    q = urllib.parse.urlencode(
        {"query.bibliographic": c["title"], "query.author": c.get("author", ""), "rows": 3}
    )
    items = get(f"https://api.crossref.org/works?{q}")["message"]["items"]
    best, best_s = None, -1.0
    for it in items:
        r = from_crossref(it)
        s = score(c["title"], r["title"])
        if s > best_s:
            best, best_s = r, s
    return best


def main():
    cands = json.load(open(sys.argv[1]))
    out = []
    for i, c in enumerate(cands, 1):
        rec = {"key": c["key"], "section": c["section"], "expected": c["title"]}
        try:
            r = resolve(c)
            rec.update(r or {})
            rec["match"] = score(c["title"], (r or {}).get("title", ""))
            rec["author_ok"] = norm(c.get("author", "")) in norm(" ".join((r or {}).get("authors", [])))
        except Exception as e:  # noqa: BLE001 - report, never crash the batch
            rec["error"] = f"{type(e).__name__}: {e}"
            rec["match"] = 0.0
        out.append(rec)
        flag = "OK " if rec.get("match", 0) >= 0.85 else "?? "
        if rec.get("error"):
            flag = "ERR"
        print(
            f"{flag} {i:3d} [{rec['section']}] {rec['key']:<24} m={rec.get('match',0):.2f} "
            f"auth={rec.get('author_ok')} {str(rec.get('year')):<6} {rec.get('title','')[:78]}"
        )
        if rec.get("error"):
            print(f"        -> {rec['error']}")
        time.sleep(0.12)
    json.dump(out, open(sys.argv[2], "w"), indent=1)
    ok = sum(1 for r in out if r.get("match", 0) >= 0.85)
    print(f"\n{ok}/{len(out)} matched >=0.85")


if __name__ == "__main__":
    main()
