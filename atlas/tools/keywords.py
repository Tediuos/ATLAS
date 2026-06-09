"""Keyword research via Google Autocomplete and LLM semantic clustering."""
import json
import time

import httpx

from atlas.llm import get_llm_client


GOOGLE_AUTOCOMPLETE_URL = "https://suggestqueries.google.com/complete/search"
_EXPAND_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def research_keywords(
    seed_keyword: str, language: str = "en", max_suggestions: int = 50
) -> dict:
    """
    Research keywords using Google Autocomplete and LLM-based clustering.

    Fetches suggestions for the seed keyword plus alphabetical expansions,
    then calls the LLM to group them into semantic clusters and classify
    each keyword's search intent.

    Args:
        seed_keyword: Primary keyword or topic to research.
        language: BCP-47 language code (default: "en").
        max_suggestions: Maximum number of unique keywords to collect.

    Returns:
        Dict with keys: seed, total, keywords (ranked list), clusters (dict).
    """
    print(f"[Keywords] Fetching autocomplete for: {seed_keyword}")
    raw = _fetch_google_autocomplete(seed_keyword, language)

    expanded: set[str] = set(raw)
    for letter in _EXPAND_LETTERS:
        if len(expanded) >= max_suggestions:
            break
        time.sleep(0.1)  # polite crawl rate
        variants = _fetch_google_autocomplete(f"{seed_keyword} {letter}", language)
        expanded.update(variants[:5])

    keyword_list = list(expanded)[:max_suggestions]

    print(f"[Keywords] {len(keyword_list)} keywords collected. Clustering with LLM...")
    clusters = _cluster_with_llm(seed_keyword, keyword_list)

    ranked = _rank_keywords(keyword_list, clusters)

    return {
        "seed": seed_keyword,
        "total": len(ranked),
        "keywords": ranked,
        "clusters": clusters,
    }


def _fetch_google_autocomplete(query: str, language: str = "en") -> list[str]:
    """
    Fetch keyword suggestions from the Google Autocomplete (Suggest) API.

    Uses the Firefox client parameter which returns a plain JSON array.
    Returns an empty list on any network or parse error.
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                GOOGLE_AUTOCOMPLETE_URL,
                params={"q": query, "client": "firefox", "hl": language},
                headers={"User-Agent": "Mozilla/5.0 (compatible; AtlasSEOBot/0.1)"},
            )
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
                return data[1]
    except Exception:
        pass
    return []


def _cluster_with_llm(seed: str, keywords: list[str]) -> dict:
    """
    Use the LLM to semantically cluster keywords and classify search intent.

    Returns a dict of cluster_name → {description, keywords: [{keyword, intent, volume_rank}]}.
    Falls back to a single 'ungrouped' cluster on LLM/parse failure.
    """
    if not keywords:
        return {}

    prompt = (
        f'You are an SEO expert. Analyse these keywords related to "{seed}" and:\n'
        "1. Group them into 3-6 semantic clusters\n"
        "2. Classify each keyword's intent as: informational, commercial, or transactional\n"
        "3. Assign a relative volume rank 1-10 (10 = highest estimated volume)\n\n"
        f"Keywords:\n{json.dumps(keywords, indent=2)}\n\n"
        "Return a JSON object:\n"
        '{\n  "clusters": {\n    "cluster_name": {\n'
        '      "description": "what this cluster covers",\n'
        '      "keywords": [\n'
        '        {"keyword": "...", "intent": "informational|commercial|transactional", "volume_rank": 1}\n'
        "      ]\n    }\n  }\n}\n\n"
        "Return ONLY the JSON, no additional text."
    )

    client, model = get_llm_client()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        data = json.loads(content)
        return data.get("clusters", {})
    except Exception:
        return {
            "ungrouped": {
                "description": "All keywords",
                "keywords": [
                    {"keyword": kw, "intent": "informational", "volume_rank": 5}
                    for kw in keywords
                ],
            }
        }


def _rank_keywords(keywords: list[str], clusters: dict) -> list[dict]:
    """
    Build a flat ranked keyword list from cluster data, sorted by volume_rank desc.

    Keywords not captured by the LLM are included with default values.
    """
    keyword_data: dict[str, dict] = {}
    for cluster_name, cluster_info in clusters.items():
        for item in cluster_info.get("keywords") or []:
            kw = item.get("keyword", "")
            if kw:
                keyword_data[kw] = {
                    "keyword": kw,
                    "cluster": cluster_name,
                    "intent": item.get("intent", "informational"),
                    "volume_rank": item.get("volume_rank", 5),
                }

    for kw in keywords:
        if kw not in keyword_data:
            keyword_data[kw] = {
                "keyword": kw,
                "cluster": "other",
                "intent": "informational",
                "volume_rank": 3,
            }

    return sorted(keyword_data.values(), key=lambda x: x["volume_rank"], reverse=True)
