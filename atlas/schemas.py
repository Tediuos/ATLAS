"""Validated contracts at the model, tool and review boundaries."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuditInput(Contract):
    url: str = Field(min_length=8, max_length=2048)

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        from atlas.network import validate_url

        return validate_url(value, resolve=False)


class KeywordInput(Contract):
    seed_keyword: Text
    language: str = Field(default="en", pattern=r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")


class ArticleInput(Contract):
    target_keyword: Text
    context: str = Field(default="", max_length=12000)
    audience: Text = "general"


class PublishInput(Contract):
    """Only the validated article in state can be sent to WordPress."""

    status: Literal["draft", "publish", "private"] = "draft"


class LinkedInDraftInput(Contract):
    topic: Text
    context: str = Field(default="", max_length=8000)
    audience: Text = "professional network"


class LinkedInPublishInput(Contract):
    visibility: Literal["PUBLIC"] = "PUBLIC"


class LinkedInPost(Contract):
    text: str = Field(min_length=1, max_length=3000)


class CriterionScore(Contract):
    score: int = Field(ge=1, le=5, strict=True)
    rationale: str = Field(min_length=10, max_length=1500)


class JudgeScores(Contract):
    relevance: CriterionScore
    clarity: CriterionScore
    structure: CriterionScore
    seo: CriterionScore
    factual_support: CriterionScore
    recommendation: Literal["accept", "revise", "reject"]
    requires_fact_check: bool = Field(strict=True)
    concerns: list[Text] = Field(default_factory=list, max_length=10)


class Issue(Contract):
    priority: int = Field(ge=1, le=10)
    category: Literal["technical", "on-page", "content", "performance", "structured-data", "mobile"]
    issue: Text
    impact: Text
    recommendation: Text
    effort: Literal["low", "medium", "high"]


class AuditAnalysis(Contract):
    issues: list[Issue] = Field(max_length=10)


class KeywordItem(Contract):
    keyword: Text
    intent: Literal["informational", "commercial", "transactional", "navigational"]
    volume_rank: int = Field(ge=1, le=10, description="Model heuristic, not measured search volume")


class Cluster(Contract):
    description: Text
    keywords: list[KeywordItem] = Field(max_length=100)


class KeywordClusters(Contract):
    clusters: dict[str, Cluster]


class Subsection(Contract):
    h3: Text
    key_points: list[Text] = Field(max_length=10)


class Section(Contract):
    h2: Text
    key_points: list[Text] = Field(min_length=1, max_length=10)
    subsections: list[Subsection] = Field(default_factory=list, max_length=5)


class FAQ(Contract):
    question: Text
    answer: str = Field(min_length=1, max_length=2000)


class ArticleOutline(Contract):
    title: Text
    meta_description: str = Field(min_length=50, max_length=165)
    intro_hook: str = Field(min_length=1, max_length=2000)
    sections: list[Section] = Field(min_length=4, max_length=6)
    faq: list[FAQ] = Field(min_length=1, max_length=5)
    conclusion_points: list[Text] = Field(min_length=1, max_length=5)


class Article(Contract):
    target_keyword: Text
    title: Text
    html_content: str = Field(min_length=1, max_length=100000)
    faq_json_ld: str = Field(default="", max_length=20000)
    meta_description: str = Field(min_length=50, max_length=165)
    word_count: int = Field(ge=1)


class Approval(Contract):
    approved: bool = Field(strict=True)
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class HarnessConfig(Contract):
    max_iterations: int = Field(default=12, ge=1, le=50)
    max_tool_calls: int = Field(default=20, ge=1, le=100)
    max_model_calls: int = Field(default=40, ge=1, le=200)
    max_tokens: int = Field(default=60000, ge=1)
    max_context_chars: int = Field(default=32000, ge=2000, le=200000)
    max_tool_result_chars: int = Field(default=6000, ge=256, le=20000)
    max_retries: int = Field(default=2, ge=0, le=4)
    retry_delay: float = Field(default=0.5, ge=0, le=10)
