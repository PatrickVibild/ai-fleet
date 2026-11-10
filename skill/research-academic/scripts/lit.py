#!/usr/bin/env python3
"""Academic literature library: search OpenAlex, add papers to ~/research and Zotero, fetch full text.

  lit.py search QUERY [--limit N] [--since YEAR]
  lit.py refs DOI [--limit N]          works DOI cites, most cited first
  lit.py cited-by DOI [--limit N]      works citing DOI, most cited first
  lit.py add DOI|arXiv:ID --topic T    or: add --csl FILE --topic T (hand-written CSL-JSON, for works without a DOI)
  lit.py fetch KEY                     retry getting the full text
  lit.py config                        show the config in use

Config: ~/.config/research-academic/config.toml (library, zotero_user_id, zotero_api_key, proxy_prefix, mailto).
"""
import argparse
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import tomllib
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("RESEARCH_ACADEMIC_CONFIG", Path.home() / ".config/research-academic/config.toml"))
UA_BROWSER = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
UA_API = "research-academic/1.0"
STOPWORDS = {"a", "an", "the", "on", "of", "in", "for", "and", "to", "with", "from", "by", "at", "is", "are", "towards", "toward"}
PUBLISHER_PAUSE_S = 3


def load_config():
    cfg = {"library": "~/research", "zotero_user_id": "", "zotero_api_key": "", "proxy_prefix": "", "mailto": ""}
    if CONFIG_PATH.exists():
        cfg.update(tomllib.loads(CONFIG_PATH.read_text()))
    shared = Path.home() / ".config/zotero/env"  # ZOTERO_USER_ID / ZOTERO_API_KEY, also used by other tools
    if shared.exists() and not (cfg["zotero_user_id"] and cfg["zotero_api_key"]):
        env = dict(l.split("=", 1) for l in shared.read_text().splitlines() if "=" in l and not l.startswith("#"))
        cfg["zotero_user_id"] = env.get("ZOTERO_USER_ID", "").strip().strip('"\'')
        cfg["zotero_api_key"] = env.get("ZOTERO_API_KEY", "").strip().strip('"\'')
    cfg["library"] = Path(cfg["library"]).expanduser()
    return cfg


CFG = load_config()
LIB = CFG["library"]


def http(url, headers=None, data=None, method=None, timeout=30):
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": UA_API, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, dict(r.headers), r.read(), r.geturl()


def get_json(url, headers=None):
    return json.loads(http(url, {"Accept": "application/json", **(headers or {})})[2])


# --- OpenAlex ---------------------------------------------------------------

OA_SELECT = "id,doi,title,publication_year,cited_by_count,authorships,primary_location,type"


def openalex(path, **params):
    if CFG["mailto"]:
        params["mailto"] = CFG["mailto"]
    return get_json(f"https://api.openalex.org/{path}?{urllib.parse.urlencode(params)}")


def oa_work(doi):
    try:
        return openalex(f"works/doi:{doi}")
    except urllib.error.HTTPError:
        return None


def print_works(works):
    known = {v["doi"].lower() for v in library().values() if v.get("doi")}
    for w in works:
        doi = (w.get("doi") or "").removeprefix("https://doi.org/")
        authors = w.get("authorships") or []
        first = authors[0]["author"]["display_name"] if authors else "?"
        etal = " et al." if len(authors) > 1 else ""
        venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        mark = "*" if doi and doi.lower() in known else " "
        print(f"{mark} {w.get('publication_year')}  cites={w.get('cited_by_count'):<6} {doi or '(no doi)'}")
        print(f"    {w.get('title')} — {first}{etal}{' · ' + venue if venue else ''}")
    print("(* = already in the library)")


def cmd_search(a):
    params = {"search": a.query, "per-page": a.limit, "select": OA_SELECT}
    if a.since:
        params["filter"] = f"from_publication_date:{a.since}-01-01"
    print_works(openalex("works", **params)["results"])


def cmd_refs(a):
    w = oa_work(normalize_id(a.doi))
    if not w:
        sys.exit("OpenAlex doesn't know that DOI")
    ids = [r.rsplit("/", 1)[1] for r in w.get("referenced_works", [])]
    works = []
    for i in range(0, len(ids), 50):
        works += openalex("works", filter="openalex_id:" + "|".join(ids[i:i + 50]), select=OA_SELECT, **{"per-page": 50})["results"]
    works.sort(key=lambda x: -(x.get("cited_by_count") or 0))
    print_works(works[: a.limit])


def cmd_cited_by(a):
    w = oa_work(normalize_id(a.doi))
    if not w:
        sys.exit("OpenAlex doesn't know that DOI")
    wid = w["id"].rsplit("/", 1)[1]
    print_works(openalex("works", filter=f"cites:{wid}", sort="cited_by_count:desc", select=OA_SELECT, **{"per-page": a.limit})["results"])


def oa_abstract(w):
    inv = (w or {}).get("abstract_inverted_index")
    if not inv:
        return ""
    pos = sorted((p, word) for word, ps in inv.items() for p in ps)
    return " ".join(word for _, word in pos)


# --- metadata ---------------------------------------------------------------

def normalize_id(s):
    s = s.strip().removeprefix("https://doi.org/").removeprefix("http://dx.doi.org/").removeprefix("doi:")
    m = re.match(r"(?i)arxiv:(.+)", s)
    if m:
        return "10.48550/arXiv." + re.sub(r"v\d+$", "", m.group(1))
    return s


def csl_for_doi(doi):
    _, _, body, _ = http(f"https://doi.org/{urllib.parse.quote(doi)}", {"Accept": "application/vnd.citationstyles.csl+json"})
    return json.loads(body)


def first(v):
    return (v[0] if v else "") if isinstance(v, list) else (v or "")


def csl_year(c):
    for k in ("issued", "published-print", "published-online", "published", "created"):
        parts = (c.get(k) or {}).get("date-parts") or [[None]]
        if parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


KIND = {  # CSL/Crossref type -> (bibtex type, Zotero itemType)
    "journal-article": ("article", "journalArticle"), "article-journal": ("article", "journalArticle"),
    "proceedings-article": ("inproceedings", "conferencePaper"), "paper-conference": ("inproceedings", "conferencePaper"),
    "book": ("book", "book"), "monograph": ("book", "book"), "edited-book": ("book", "book"),
    "book-chapter": ("incollection", "bookSection"), "chapter": ("incollection", "bookSection"),
    "posted-content": ("misc", "preprint"), "article": ("misc", "preprint"),
    "report": ("techreport", "report"), "dissertation": ("phdthesis", "thesis"), "thesis": ("phdthesis", "thesis"),
}


def ascii_slug(s):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower())


def make_key(c, lib):
    authors = c.get("author") or c.get("editor") or [{}]
    name = ascii_slug(authors[0].get("family") or authors[0].get("literal") or "anon") or "anon"
    words = [ascii_slug(w) for w in re.split(r"\s+", first(c.get("title")))]
    word = next((w for w in words if w and w not in STOPWORDS), "")
    base = f"{name}{csl_year(c) or ''}{word}"
    key, n = base, 1
    while key in lib:
        n += 1
        key = f"{base}{chr(ord('a') + n - 1)}"
    return key


def bib_escape(s):
    return str(s).replace("{", "").replace("}", "")


def to_bibtex(key, c):
    btype = KIND.get(c.get("type"), ("misc", ""))[0]
    authors = " and ".join(
        f"{a['family']}, {a.get('given', '')}".strip(", ") if a.get("family") else a.get("literal", "")
        for a in (c.get("author") or []))
    container = first(c.get("container-title"))
    fields = {
        "title": "{" + bib_escape(first(c.get("title"))) + "}",
        "author": authors,
        "editor": " and ".join(f"{a.get('family', '')}, {a.get('given', '')}" for a in c.get("editor") or []) if btype in ("book", "incollection") and not authors else "",
        "year": csl_year(c),
        "journal" if btype == "article" else "booktitle": container if btype in ("article", "inproceedings", "incollection") else "",
        "volume": c.get("volume"), "number": c.get("issue"), "pages": str(c.get("page") or "").replace("-", "--"),
        "publisher": c.get("publisher"), "school": c.get("publisher") if btype == "phdthesis" else "",
        "isbn": first(c.get("ISBN")), "doi": c.get("DOI"), "url": c.get("URL"),
    }
    body = ",\n".join(f"  {k} = {{{bib_escape(v) if k != 'title' else v}}}" for k, v in fields.items() if v)
    return f"@{btype}{{{key},\n{body}\n}}\n"


# --- library ----------------------------------------------------------------

def library():
    p = LIB / "library.json"
    return json.loads(p.read_text()) if p.exists() else {}


def save_library(lib):
    (LIB / "library.json").write_text(json.dumps(lib, indent=1, ensure_ascii=False) + "\n")


def ensure_layout():
    for d in ("papers", "topics", "pdf", "text"):
        (LIB / d).mkdir(parents=True, exist_ok=True)
    if not (LIB / "INDEX.md").exists():
        (LIB / "INDEX.md").write_text("# Library topics\n\n")
    (LIB / "refs.bib").touch()


def note_stub(key, c, doi, topics, abstract):
    authors = "; ".join(f"{a.get('family', '')}, {a.get('given', '')}".strip(", ") or a.get("literal", "") for a in c.get("author") or [])
    return f"""---
key: {key}
title: {json.dumps(first(c.get('title')), ensure_ascii=False)}
authors: {json.dumps(authors, ensure_ascii=False)}
year: {csl_year(c)}
venue: {json.dumps(first(c.get('container-title')) or c.get('publisher') or '', ensure_ascii=False)}
doi: {doi or ''}
topics: [{', '.join(topics)}]
fulltext: none
---

## Abstract

{abstract or '(no abstract available)'}

## Notes

<!-- filled in after reading: Claim, Method, Results, Values (with page/table), Quotes (with page), Relevance -->
"""


def set_frontmatter(key, field, value):
    p = LIB / "papers" / f"{key}.md"
    text = p.read_text()
    text = re.sub(rf"(?m)^{field}: .*$", f"{field}: {value}", text, count=1)
    p.write_text(text)


def cmd_add(a):
    ensure_layout()
    lib = library()
    if a.csl:
        c = json.loads(Path(a.csl).read_text())
        doi = c.get("DOI", "")
    else:
        doi = normalize_id(a.id)
        c = None
    existing = next((k for k, v in lib.items() if doi and v.get("doi", "").lower() == doi.lower()), None)
    if existing:
        topics = lib[existing].setdefault("topics", [])
        if a.topic not in topics:
            topics.append(a.topic)
            set_frontmatter(existing, "topics", "[" + ", ".join(topics) + "]")
            save_library(lib)
            zotero_add(existing, lib[existing].get("csl"), a.topic)
        print(f"already in library: {existing}  (papers/{existing}.md, fulltext: {lib[existing].get('fulltext')})")
        return
    if c is None:
        try:
            c = csl_for_doi(doi)
        except urllib.error.HTTPError as e:
            sys.exit(f"no metadata for {doi}: HTTP {e.code}. Write CSL-JSON by hand and use --csl.")
    w = oa_work(doi) if doi else None
    abstract = oa_abstract(w) or re.sub(r"<[^>]+>", "", html.unescape(c.get("abstract", ""))).strip()
    key = make_key(c, lib)
    with open(LIB / "refs.bib", "a") as f:
        f.write("\n" + to_bibtex(key, c))
    (LIB / "papers" / f"{key}.md").write_text(note_stub(key, c, doi, [a.topic], abstract))
    slim = {k: c[k] for k in ("type", "title", "author", "editor", "issued", "container-title", "volume", "issue", "page",
                               "publisher", "DOI", "URL", "ISBN", "ISSN") if k in c}
    if abstract:
        slim["abstract"] = abstract
    lib[key] = {"doi": doi, "title": first(c.get("title")), "topics": [a.topic], "fulltext": "none", "csl": slim,
                "oa_pdf_urls": oa_pdf_urls(w)}
    save_library(lib)
    print(f"added {key}  -> papers/{key}.md, refs.bib")
    zotero_add(key, slim, a.topic)
    fetch_fulltext(key)


# --- full text --------------------------------------------------------------

def oa_pdf_urls(w):
    if not w:
        return []
    urls = [(w.get("best_oa_location") or {}).get("pdf_url")] + [l.get("pdf_url") for l in w.get("locations") or []]
    return list(dict.fromkeys(u for u in urls if u))


def download_pdf(url, dest, referer=None):
    """Return True if url gave a PDF. Follows a landing page's citation_pdf_url once."""
    headers = {"User-Agent": UA_BROWSER, "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    try:
        _, hdrs, body, final = http(url, headers, timeout=60)
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"    {url}: {getattr(e, 'code', '') or e}")
        return False
    if body[:5] == b"%PDF-":
        dest.write_bytes(body)
        return True
    m = re.search(rb'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)', body) or \
        re.search(rb'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url', body)
    if m and not referer:
        time.sleep(PUBLISHER_PAUSE_S)
        return download_pdf(urllib.parse.urljoin(final, html.unescape(m.group(1).decode())), dest, referer=final)
    print(f"    {url}: got {hdrs.get('Content-Type', '?')}, no PDF")
    return False


def zotero_storage_pdf(doi):
    db = Path.home() / "Zotero/zotero.sqlite"
    if not doi or not db.exists():
        return None
    con = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
    rows = con.execute("""
        SELECT att.key, ia.path FROM items i
        JOIN itemData d ON d.itemID = i.itemID JOIN fields f ON f.fieldID = d.fieldID AND f.fieldName = 'DOI'
        JOIN itemDataValues v ON v.valueID = d.valueID
        JOIN itemAttachments ia ON ia.parentItemID = i.itemID JOIN items att ON att.itemID = ia.itemID
        WHERE lower(v.value) = lower(?) AND ia.contentType = 'application/pdf'""", (doi,)).fetchall()
    con.close()
    for att_key, path in rows:
        if path and path.startswith("storage:"):
            p = Path.home() / "Zotero/storage" / att_key / path.removeprefix("storage:")
            if p.exists():
                return p
    return None


def fetch_fulltext(key):
    lib = library()
    entry = lib[key]
    doi = entry.get("doi", "")
    pdf = LIB / "pdf" / f"{key}.pdf"
    got = None
    local = zotero_storage_pdf(doi)
    if local:
        shutil.copy(local, pdf)
        got = "zotero storage"
    if not got and doi.lower().startswith("10.48550/arxiv."):
        if download_pdf("https://arxiv.org/pdf/" + doi.split(".", 2)[2], pdf):
            got = "arXiv"
    for url in entry.get("oa_pdf_urls", []) if not got else []:
        if download_pdf(url, pdf):
            got = "open access"
            break
    if not got and doi:
        time.sleep(PUBLISHER_PAUSE_S)
        url = f"https://doi.org/{doi}"
        if CFG["proxy_prefix"]:
            url = CFG["proxy_prefix"] + urllib.parse.quote(url, safe="")
        if download_pdf(url, pdf):
            got = "publisher"
    if got:
        txt = LIB / "text" / f"{key}.txt"
        subprocess.run(["pdftotext", "-q", str(pdf), str(txt)], check=False)
        pages = len(txt.read_text(errors="ignore").split("\f")) if txt.exists() else 0
        entry["fulltext"] = f"text/{key}.txt"
        print(f"  full text from {got}: text/{key}.txt ({pages} pages)")
    else:
        entry["fulltext"] = "abstract-only"
        print(f"  full text: not reachable. Note is abstract-only. Ask the user for this one: https://doi.org/{doi}" if doi
              else "  full text: no DOI to fetch with. Note is abstract-only.")
    set_frontmatter(key, "fulltext", entry["fulltext"])
    save_library(lib)


def cmd_fetch(a):
    if a.key not in library():
        sys.exit(f"{a.key} isn't in the library")
    fetch_fulltext(a.key)


# --- Zotero -----------------------------------------------------------------

ZOTERO_FIELDS = {  # itemType -> container field, and fields valid for that type
    "journalArticle": ("publicationTitle", {"volume", "issue", "pages", "DOI", "ISSN"}),
    "conferencePaper": ("proceedingsTitle", {"pages", "DOI", "publisher"}),
    "book": (None, {"publisher", "ISBN"}),
    "bookSection": ("bookTitle", {"pages", "publisher", "ISBN"}),
    "preprint": ("repository", {"DOI"}),
    "report": (None, {"pages", "institution"}),
    "thesis": (None, {"university"}),
}


def zotero_item(key, c):
    itype = KIND.get(c.get("type"), ("misc", "journalArticle"))[1] or "journalArticle"
    container, allowed = ZOTERO_FIELDS[itype]
    year = csl_year(c)
    item = {
        "itemType": itype, "title": first(c.get("title")), "date": str(year or ""), "url": c.get("URL", ""),
        "abstractNote": c.get("abstract", ""),
        "creators": [{"creatorType": "author", "lastName": a.get("family", ""), "firstName": a.get("given", "")}
                     if a.get("family") else {"creatorType": "author", "name": a.get("literal", "")}
                     for a in c.get("author") or []] +
                    [{"creatorType": "editor", "lastName": a.get("family", ""), "firstName": a.get("given", "")}
                     for a in c.get("editor") or []],
    }
    extra = [f"Citation Key: {key}"]
    if container and first(c.get("container-title")):
        item[container] = first(c.get("container-title"))
    values = {"volume": c.get("volume"), "issue": c.get("issue"), "pages": c.get("page"), "DOI": c.get("DOI"),
              "ISSN": first(c.get("ISSN")), "ISBN": first(c.get("ISBN")), "publisher": c.get("publisher"),
              "institution": c.get("publisher"), "university": c.get("publisher")}
    for f, v in values.items():
        if v and f in allowed:
            item[f] = str(v)
    if c.get("DOI") and "DOI" not in allowed:
        extra.append(f"DOI: {c['DOI']}")
    item["extra"] = "\n".join(extra)
    return item


def zotero_add(key, c, topic):
    lib = library()
    if CFG["zotero_user_id"] and CFG["zotero_api_key"]:
        msg = zotero_web(key, c, topic, lib)
    else:
        msg = zotero_connector(key, c, topic)
    print(f"  zotero: {msg}")


def zotero_web(key, c, topic, lib):
    base = f"https://api.zotero.org/users/{CFG['zotero_user_id']}"
    h = {"Zotero-API-Key": CFG["zotero_api_key"], "Zotero-API-Version": "3", "Content-Type": "application/json"}
    try:
        coll = next((x["key"] for x in get_json(f"{base}/collections?limit=100", h) if x["data"]["name"] == topic), None)
        if not coll:
            _, _, body, _ = http(f"{base}/collections", h, json.dumps([{"name": topic}]).encode(), "POST")
            coll = json.loads(body)["successful"]["0"]["key"]
        zkey = lib.get(key, {}).get("zotero")
        if zkey:  # already in Zotero: add the collection
            item = get_json(f"{base}/items/{zkey}", h)
            cols = set(item["data"].get("collections", [])) | {coll}
            http(f"{base}/items/{zkey}", {**h, "If-Unmodified-Since-Version": str(item["version"])},
                 json.dumps({"collections": sorted(cols)}).encode(), "PATCH")
            return f"item {zkey} added to collection '{topic}'"
        item = zotero_item(key, c)
        item["collections"] = [coll]
        _, _, body, _ = http(f"{base}/items", h, json.dumps([item]).encode(), "POST")
        res = json.loads(body)
        if res.get("failed"):
            return f"failed: {res['failed']}"
        zkey = res["successful"]["0"]["key"]
        lib[key]["zotero"] = zkey
        save_library(lib)
        return f"item {zkey} in collection '{topic}' (web API; appears in the desktop app after it syncs)"
    except urllib.error.HTTPError as e:
        return f"web API error {e.code}: {e.read()[:200]!r}"


def zotero_connector(key, c, topic):
    base = "http://127.0.0.1:23119/connector"
    h = {"Content-Type": "application/json", "X-Zotero-Connector-API-Version": "3"}
    try:
        _, _, body, _ = http(f"{base}/getSelectedCollection", h, b"{}", "POST", timeout=5)
    except (urllib.error.URLError, TimeoutError):
        return "not added: no web API key configured and the Zotero app isn't running"
    targets = json.loads(body).get("targets", [])
    target = next((t["id"] for t in targets if t.get("name") == topic), None)
    session = str(uuid.uuid4())
    item = zotero_item(key, c)
    item["id"] = key
    http(f"{base}/saveItems", h, json.dumps({"sessionID": session, "items": [item]}).encode(), "POST")
    if target:
        http(f"{base}/updateSession", h, json.dumps({"sessionID": session, "target": target}).encode(), "POST")
        return f"saved to collection '{topic}' (desktop app)"
    return f"saved to the collection selected in Zotero; there is no collection named '{topic}' (desktop app can't create one)"


def cmd_config(_):
    print(f"config file: {CONFIG_PATH} ({'exists' if CONFIG_PATH.exists() else 'missing, using defaults'})")
    print(f"library:     {LIB}")
    print(f"zotero:      {'web API, user ' + CFG['zotero_user_id'] if CFG['zotero_api_key'] else 'desktop connector (app must be open)'}")
    print(f"proxy:       {CFG['proxy_prefix'] or '(none: publisher access only on the university network)'}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--limit", type=int, default=15); s.add_argument("--since", type=int)
    s.set_defaults(fn=cmd_search)
    for name, fn in (("refs", cmd_refs), ("cited-by", cmd_cited_by)):
        s = sub.add_parser(name); s.add_argument("doi"); s.add_argument("--limit", type=int, default=20); s.set_defaults(fn=fn)
    s = sub.add_parser("add"); s.add_argument("id", nargs="?"); s.add_argument("--csl"); s.add_argument("--topic", required=True)
    s.set_defaults(fn=cmd_add)
    s = sub.add_parser("fetch"); s.add_argument("key"); s.set_defaults(fn=cmd_fetch)
    sub.add_parser("config").set_defaults(fn=cmd_config)
    a = p.parse_args()
    if a.cmd == "add" and not (a.id or a.csl):
        p.error("add needs a DOI, arXiv:ID or --csl FILE")
    a.fn(a)


if __name__ == "__main__":
    main()
