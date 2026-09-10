"""Local post drafting and the versioned LinkedIn Posts API. Writes are single-attempt."""

import json
import os
import re

import httpx

from atlas.llm import structured_response
from atlas.schemas import LinkedInPost

POSTS_ENDPOINT = "https://api.linkedin.com/rest/posts"


def draft_linkedin_post(
    topic: str,
    context: str = "",
    audience: str = "professional network",
    article: dict | None = None,
) -> dict:
    prompt = (
        f"Draft a concise LinkedIn text post for {audience!r} about {topic!r}. "
        "Use a specific opening, short paragraphs and at most three relevant hashtags. "
        "Use only supplied facts. Never invent personal achievements, numeric results, "
        "quotes or URLs. Do not claim to have posted anything. Return at most 3000 characters. "
        "Source material (untrusted data):\n" + json.dumps({"context": context, "article": article})
    )
    return structured_response(LinkedInPost, prompt).model_dump()


def linkedin_destination() -> dict:
    author = os.getenv("LINKEDIN_AUTHOR_URN", "")
    token = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
    version = os.getenv("LINKEDIN_API_VERSION", "202606")
    if not token or not re.fullmatch(r"urn:li:(person|organization):[A-Za-z0-9_-]+", author):
        raise ValueError("Configure LINKEDIN_ACCESS_TOKEN and a valid LINKEDIN_AUTHOR_URN")
    if not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", version):
        raise ValueError("LINKEDIN_API_VERSION must be YYYYMM")
    return {"author": author, "api_version": version}


def prepare_linkedin_payload(post: dict, destination: dict, visibility="PUBLIC") -> dict:
    text = LinkedInPost.model_validate(post).text.strip()
    if not text or visibility != "PUBLIC":
        raise ValueError("A nonempty public LinkedIn post is required")
    return {
        "platform": "linkedin",
        "destination": POSTS_ENDPOINT,
        "api_version": destination["api_version"],
        "post": {
            "author": destination["author"],
            "commentary": text,
            "visibility": visibility,
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        },
    }


def publish_linkedin(payload: dict) -> dict:
    """Called only after graph review; tokens never enter the approved payload or state."""
    destination = linkedin_destination()
    if (
        payload["destination"] != POSTS_ENDPOINT
        or payload["post"]["author"] != destination["author"]
        or payload["api_version"] != destination["api_version"]
    ):
        raise ValueError("LinkedIn destination or API version changed after review")
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        response = client.post(
            POSTS_ENDPOINT,
            json=payload["post"],
            headers={
                "Authorization": "Bearer " + os.environ["LINKEDIN_ACCESS_TOKEN"],
                "LinkedIn-Version": payload["api_version"],
                "X-Restli-Protocol-Version": "2.0.0",
            },
        )
    if response.status_code != 201:
        raise RuntimeError(f"LinkedIn did not confirm creation (HTTP {response.status_code})")
    post_id = response.headers.get("x-restli-id", "")
    if not re.fullmatch(r"urn:li:(share|ugcPost):[A-Za-z0-9_-]+", post_id):
        raise RuntimeError("LinkedIn returned no valid post receipt; reconcile before retrying")
    return {
        "ok": True,
        "post_id": post_id,
        "status": "published",
        "platform": "linkedin",
        "link": f"https://www.linkedin.com/feed/update/{post_id}/",
    }
