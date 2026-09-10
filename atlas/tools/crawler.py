"""Crawl une URL et extrait toutes les données SEO on-page."""

import json
import time
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

from atlas.network import safe_get

USER_AGENT = "AtlasSEOBot/0.1 (Internship Project; Python httpx)"


def crawl_url(url: str, timeout: float = 15.0) -> dict:
    """Crawl une URL et retourne un dict structuré avec toutes les données SEO."""
    start = time.time()

    # 1. Récupération de la page
    try:
        response = safe_get(url, timeout=timeout)
    except (httpx.HTTPError, ValueError, OSError) as e:
        return {"url": url, "ok": False, "error": str(e)}

    elapsed = round(time.time() - start, 3)

    if response.status_code >= 400:
        return {
            "url": url,
            "final_url": str(response.url),
            "status_code": response.status_code,
            "ok": False,
            "error": f"HTTP {response.status_code}",
            "response_time_s": elapsed,
        }

    # 2. Parsing du HTML
    html = response.text
    parser = HTMLParser(html)

    # 3. Construction du dict final
    return {
        "url": url,
        "final_url": str(response.url),
        "status_code": response.status_code,
        "redirected": str(response.url) != url,
        "response_time_s": elapsed,
        "html_size_bytes": len(html.encode("utf-8")),
        "encoding": response.encoding,
        "ok": True,
        "language": _extract_language(parser),
        "title": _extract_title(parser),
        "meta": _extract_meta_tags(parser),
        "headings": _extract_headings(parser),
        "links": _extract_links(parser, str(response.url)),
        "images": _extract_images(parser, str(response.url)),
        "open_graph": _extract_open_graph(parser),
        "twitter_card": _extract_twitter_card(parser),
        "structured_data": _extract_json_ld(parser),
    }


# ============ EXTRACTEURS INTERNES ============


def _extract_language(parser):
    html_tag = parser.css_first("html")
    return html_tag.attributes.get("lang") if html_tag else None


def _extract_title(parser):
    tag = parser.css_first("title")
    if not tag:
        return None
    text = tag.text(strip=True)
    return {"text": text, "length": len(text)}


def _extract_meta_tags(parser):
    meta = {
        "description": None,
        "keywords": None,
        "robots": None,
        "canonical": None,
        "hreflang": [],
    }

    for tag in parser.css("meta"):
        name = (tag.attributes.get("name") or "").lower()
        content = tag.attributes.get("content", "")
        if name == "description":
            meta["description"] = {"text": content, "length": len(content)}
        elif name == "keywords":
            meta["keywords"] = content
        elif name == "robots":
            meta["robots"] = content

    canonical = parser.css_first('link[rel="canonical"]')
    if canonical:
        meta["canonical"] = canonical.attributes.get("href")

    for link in parser.css('link[rel="alternate"][hreflang]'):
        meta["hreflang"].append(
            {
                "lang": link.attributes.get("hreflang"),
                "url": link.attributes.get("href"),
            }
        )

    return meta


def _extract_headings(parser):
    headings = {f"h{i}": [] for i in range(1, 7)}
    for level in range(1, 7):
        for tag in parser.css(f"h{level}"):
            text = tag.text(strip=True)
            if text:
                headings[f"h{level}"].append(text)
    headings["counts"] = {k: len(v) for k, v in headings.items() if k.startswith("h")}
    return headings


def _extract_links(parser, base_url):
    domain = urlparse(base_url).netloc
    internal, external = [], []

    for a in parser.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        absolute = urljoin(base_url, href)
        link_domain = urlparse(absolute).netloc
        rel = (a.attributes.get("rel") or "").lower()
        link_data = {
            "url": absolute,
            "anchor": a.text(strip=True)[:100],
            "nofollow": "nofollow" in rel,
        }
        (internal if link_domain == domain else external).append(link_data)

    return {
        "internal": internal,
        "external": external,
        "counts": {
            "internal": len(internal),
            "external": len(external),
            "total": len(internal) + len(external),
        },
    }


def _extract_images(parser, base_url):
    images = []
    for img in parser.css("img"):
        src = img.attributes.get("src", "")
        if not src:
            continue
        alt = img.attributes.get("alt", "") or ""
        images.append(
            {
                "src": urljoin(base_url, src),
                "alt": alt,
                "has_alt": alt.strip() != "",
                "width": img.attributes.get("width"),
                "height": img.attributes.get("height"),
            }
        )
    return {
        "list": images,
        "total": len(images),
        "missing_alt": sum(1 for i in images if not i["has_alt"]),
    }


def _extract_open_graph(parser):
    og = {}
    for tag in parser.css('meta[property^="og:"]'):
        prop = tag.attributes.get("property", "").replace("og:", "")
        og[prop] = tag.attributes.get("content", "")
    return og


def _extract_twitter_card(parser):
    tw = {}
    for tag in parser.css('meta[name^="twitter:"]'):
        name = tag.attributes.get("name", "").replace("twitter:", "")
        tw[name] = tag.attributes.get("content", "")
    return tw


def _extract_json_ld(parser):
    blocks = []
    for script in parser.css('script[type="application/ld+json"]'):
        raw = script.text() or ""
        if not raw.strip():
            continue
        try:
            blocks.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return blocks


# ============ MODE CLI ============

if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    print(f"Crawling: {target}\n")
    result = crawl_url(target)
    print(json.dumps(result, indent=2, ensure_ascii=False))
