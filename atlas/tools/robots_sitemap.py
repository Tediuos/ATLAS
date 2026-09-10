"""Bounded robots.txt and sitemap collection with redirect validation."""

from urllib.parse import urlsplit

from defusedxml.ElementTree import fromstring

from atlas.harness import safe_error
from atlas.network import safe_get


def fetch_robots_txt(base_url: str, timeout: float = 10.0) -> dict:
    parsed = urlsplit(base_url)
    url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        response = safe_get(url, timeout=timeout, max_bytes=500000)
        if response.status_code == 404:
            return {"url": url, "ok": True, "exists": False}
        response.raise_for_status()
        agents, sitemaps, active, rules_started = {}, [], [], False
        for line in response.text.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if rules_started:
                    active, rules_started = [], False
                active.append(value)
                agents.setdefault(value, {"allow": [], "disallow": [], "crawl_delay": None})
            elif key == "sitemap":
                sitemaps.append(value)
            elif key in {"allow", "disallow", "crawl-delay"}:
                rules_started = True
                for agent in active:
                    if key == "crawl-delay":
                        agents[agent]["crawl_delay"] = value
                    else:
                        agents[agent][key].append(value)
        return {
            "url": url,
            "ok": True,
            "exists": True,
            "user_agents": agents,
            "sitemaps_declared": sitemaps,
        }
    except Exception as exc:
        return {"url": url, "ok": False, "error": safe_error(exc)}


def fetch_sitemap(base_url: str, max_urls: int = 200, max_sitemaps: int = 10) -> dict:
    """Visit at most 10 XML documents and retain at most max_urls unique pages.

    When truncated, total_urls is a lower bound rather than an invented site total.
    """
    if max_urls < 1 or max_sitemaps < 1:
        raise ValueError("Sitemap limits must be positive")
    parts = urlsplit(base_url)
    root = f"{parts.scheme}://{parts.netloc}"
    robots = fetch_robots_txt(root)
    queue = list(robots.get("sitemaps_declared") or [root + "/sitemap.xml"])
    visited, pages, errors = set(), {}, []
    truncated = False
    while queue and len(visited) < max_sitemaps and len(pages) < max_urls:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            response = safe_get(url, timeout=10)
            response.raise_for_status()
            tree = fromstring(response.content)
            kind = tree.tag.rsplit("}", 1)[-1]
            if kind not in {"sitemapindex", "urlset"}:
                raise ValueError("Expected a sitemap index or URL set")
            for entry in tree:
                values = {child.tag.rsplit("}", 1)[-1]: child.text for child in entry}
                location = values.get("loc")
                if not location:
                    continue
                if kind == "sitemapindex":
                    if location not in visited and location not in queue:
                        if len(queue) < max_sitemaps:
                            queue.append(location)
                        else:
                            truncated = True
                else:
                    if len(pages) >= max_urls:
                        truncated = True
                        break
                    pages[location] = {
                        "url": location,
                        "lastmod": values.get("lastmod"),
                        "priority": values.get("priority"),
                        "changefreq": values.get("changefreq"),
                    }
        except Exception as exc:
            errors.append(safe_error(exc))
    truncated = truncated or bool(queue)
    return {
        "base": root,
        "ok": bool(visited) and not errors,
        "total_urls": len(pages),
        "sample_urls": list(pages.values()),
        "truncated": truncated,
        "total_is_exact": not truncated and not errors,
        "sitemaps_fetched": len(visited),
        "errors": errors,
    }
