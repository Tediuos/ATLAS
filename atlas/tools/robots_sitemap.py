"""Parse robots.txt et sitemap d'un site."""
import json
from urllib.parse import urlparse

import httpx
from usp.tree import sitemap_tree_for_homepage


USER_AGENT = "AtlasSEOBot/0.1"


def fetch_robots_txt(base_url: str, timeout: float = 10.0) -> dict:
    """Récupère et parse le robots.txt d'un site."""
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    robots_url = f"{root}/robots.txt"

    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(robots_url)
    except httpx.HTTPError as e:
        return {"url": robots_url, "ok": False, "error": str(e)}

    if response.status_code == 404:
        return {
            "url": robots_url,
            "ok": True,
            "exists": False,
            "warning": "Aucun robots.txt trouvé (404). Le site autorise par défaut tout le crawling.",
        }

    if response.status_code >= 400:
        return {
            "url": robots_url,
            "ok": False,
            "status_code": response.status_code,
            "error": f"HTTP {response.status_code}",
        }

    content = response.text
    user_agents = {}
    sitemaps_declared = []
    current_agent = "*"

    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue

        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()

        if key == "user-agent":
            current_agent = value
            user_agents.setdefault(current_agent, {"allow": [], "disallow": [], "crawl_delay": None})
        elif key == "disallow":
            user_agents.setdefault(current_agent, {"allow": [], "disallow": [], "crawl_delay": None})["disallow"].append(value)
        elif key == "allow":
            user_agents.setdefault(current_agent, {"allow": [], "disallow": [], "crawl_delay": None})["allow"].append(value)
        elif key == "crawl-delay":
            user_agents.setdefault(current_agent, {"allow": [], "disallow": [], "crawl_delay": None})["crawl_delay"] = value
        elif key == "sitemap":
            sitemaps_declared.append(value)

    return {
        "url": robots_url,
        "ok": True,
        "exists": True,
        "size_bytes": len(content),
        "user_agents": user_agents,
        "sitemaps_declared": sitemaps_declared,
    }


def fetch_sitemap(base_url: str, max_urls: int = 100) -> dict:
    """Parcourt le sitemap d'un site (gère les sitemap index imbriqués)."""
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"

    try:
        tree = sitemap_tree_for_homepage(root)
    except Exception as e:
        return {"base": root, "ok": False, "error": f"{type(e).__name__}: {e}"}

    all_pages = list(tree.all_pages())
    total = len(all_pages)

    sample = []
    for page in all_pages[:max_urls]:
        sample.append({
            "url": page.url,
            "lastmod": page.last_modified.isoformat() if page.last_modified else None,
            "priority": page.priority,
            "changefreq": page.change_frequency.value if page.change_frequency else None,
        })

    return {
        "base": root,
        "ok": True,
        "total_urls": total,
        "sample_urls": sample,
        "truncated": total > max_urls,
    }


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"

    print("=" * 60)
    print(f"robots.txt — {target}")
    print("=" * 60)
    print(json.dumps(fetch_robots_txt(target), indent=2, ensure_ascii=False))

    print("\n" + "=" * 60)
    print(f"sitemap — {target}")
    print("=" * 60)
    print(json.dumps(fetch_sitemap(target), indent=2, ensure_ascii=False))