"""SQLite database models and helpers using SQLAlchemy 2.x."""
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import Column, DateTime, Float, Integer, JSON, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Session


DB_PATH = Path("atlas.db")

_engine = None


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class Mission(Base):
    """Represents an Atlas agent mission."""

    __tablename__ = "missions"

    id = Column(Integer, primary_key=True)
    text = Column(Text, nullable=False)
    url = Column(String, nullable=False)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    summary = Column(Text, nullable=True)


class Audit(Base):
    """Stores a complete SEO audit result for a URL."""

    __tablename__ = "audits"

    id = Column(Integer, primary_key=True)
    mission_id = Column(Integer, nullable=False)
    url = Column(String, nullable=False)
    crawl_data = Column(JSON, nullable=True)
    lighthouse_data = Column(JSON, nullable=True)
    robots_data = Column(JSON, nullable=True)
    sitemap_data = Column(JSON, nullable=True)
    issues = Column(JSON, nullable=True)
    score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Keyword(Base):
    """Stores keyword research results for a seed keyword."""

    __tablename__ = "keywords"

    id = Column(Integer, primary_key=True)
    mission_id = Column(Integer, nullable=False)
    seed = Column(String, nullable=False)
    keywords = Column(JSON, nullable=True)
    clusters = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Article(Base):
    """Stores a generated SEO article."""

    __tablename__ = "articles"

    id = Column(Integer, primary_key=True)
    mission_id = Column(Integer, nullable=False)
    target_keyword = Column(String, nullable=False)
    title = Column(String, nullable=True)
    html_content = Column(Text, nullable=True)
    faq_json_ld = Column(Text, nullable=True)
    meta_description = Column(String, nullable=True)
    word_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PublishLog(Base):
    """Tracks WordPress publish attempts for articles."""

    __tablename__ = "publish_logs"

    id = Column(Integer, primary_key=True)
    mission_id = Column(Integer, nullable=False)
    article_id = Column(Integer, nullable=False)
    wp_post_id = Column(Integer, nullable=True)
    wp_url = Column(String, nullable=True)
    status = Column(String, default="pending")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


def get_engine():
    """Return the SQLAlchemy engine, creating tables on first call."""
    global _engine
    if _engine is None:
        _engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
        Base.metadata.create_all(_engine)
    return _engine


def get_session() -> Session:
    """Return a new SQLAlchemy session."""
    return Session(get_engine())


# ============ MISSION HELPERS ============


def save_mission(text: str, url: str) -> int:
    """Save a new mission and return its ID."""
    with get_session() as session:
        mission = Mission(text=text, url=url, status="running")
        session.add(mission)
        session.commit()
        return mission.id


def fetch_mission(mission_id: int) -> Optional[dict]:
    """Fetch a mission by ID, returning None if not found."""
    with get_session() as session:
        mission = session.get(Mission, mission_id)
        if not mission:
            return None
        return {
            "id": mission.id,
            "text": mission.text,
            "url": mission.url,
            "status": mission.status,
            "created_at": mission.created_at.isoformat() if mission.created_at else None,
            "completed_at": mission.completed_at.isoformat() if mission.completed_at else None,
            "summary": mission.summary,
        }


def update_mission(mission_id: int, **kwargs) -> None:
    """Update arbitrary fields on a mission row."""
    with get_session() as session:
        mission = session.get(Mission, mission_id)
        if mission:
            for key, value in kwargs.items():
                setattr(mission, key, value)
            session.commit()


def list_missions() -> list[dict]:
    """List all missions ordered by newest first."""
    with get_session() as session:
        stmt = select(Mission).order_by(Mission.id.desc())
        return [
            {
                "id": m.id,
                "text": m.text[:80],
                "url": m.url,
                "status": m.status,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in session.scalars(stmt).all()
        ]


# ============ AUDIT HELPERS ============


def save_audit(
    mission_id: int,
    url: str,
    crawl_data: Optional[dict] = None,
    lighthouse_data: Optional[dict] = None,
    robots_data: Optional[dict] = None,
    sitemap_data: Optional[dict] = None,
    issues: Optional[list] = None,
    score: Optional[float] = None,
) -> int:
    """Save an audit record and return its ID."""
    with get_session() as session:
        audit = Audit(
            mission_id=mission_id,
            url=url,
            crawl_data=crawl_data,
            lighthouse_data=lighthouse_data,
            robots_data=robots_data,
            sitemap_data=sitemap_data,
            issues=issues,
            score=score,
        )
        session.add(audit)
        session.commit()
        return audit.id


def fetch_audit(audit_id: int) -> Optional[dict]:
    """Fetch an audit by ID."""
    with get_session() as session:
        audit = session.get(Audit, audit_id)
        if not audit:
            return None
        return {
            "id": audit.id,
            "mission_id": audit.mission_id,
            "url": audit.url,
            "crawl_data": audit.crawl_data,
            "lighthouse_data": audit.lighthouse_data,
            "robots_data": audit.robots_data,
            "sitemap_data": audit.sitemap_data,
            "issues": audit.issues,
            "score": audit.score,
            "created_at": audit.created_at.isoformat() if audit.created_at else None,
        }


def list_audits(mission_id: int) -> list[dict]:
    """List all audits for a mission, newest first."""
    with get_session() as session:
        stmt = select(Audit).where(Audit.mission_id == mission_id).order_by(Audit.id.desc())
        return [
            {
                "id": a.id,
                "url": a.url,
                "score": a.score,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in session.scalars(stmt).all()
        ]


# ============ KEYWORD HELPERS ============


def save_keywords(mission_id: int, seed: str, keywords: list, clusters: dict) -> int:
    """Save keyword research results and return the record ID."""
    with get_session() as session:
        kw = Keyword(mission_id=mission_id, seed=seed, keywords=keywords, clusters=clusters)
        session.add(kw)
        session.commit()
        return kw.id


def fetch_keywords(keyword_id: int) -> Optional[dict]:
    """Fetch a keyword research record by ID."""
    with get_session() as session:
        kw = session.get(Keyword, keyword_id)
        if not kw:
            return None
        return {
            "id": kw.id,
            "mission_id": kw.mission_id,
            "seed": kw.seed,
            "keywords": kw.keywords,
            "clusters": kw.clusters,
            "created_at": kw.created_at.isoformat() if kw.created_at else None,
        }


def list_keywords(mission_id: int) -> list[dict]:
    """List keyword research records for a mission."""
    with get_session() as session:
        stmt = select(Keyword).where(Keyword.mission_id == mission_id).order_by(Keyword.id.desc())
        return [
            {
                "id": kw.id,
                "seed": kw.seed,
                "keyword_count": len(kw.keywords or []),
                "created_at": kw.created_at.isoformat() if kw.created_at else None,
            }
            for kw in session.scalars(stmt).all()
        ]


# ============ ARTICLE HELPERS ============


def save_article(
    mission_id: int,
    target_keyword: str,
    title: str,
    html_content: str,
    faq_json_ld: str,
    meta_description: str,
    word_count: int,
) -> int:
    """Save a generated article and return its ID."""
    with get_session() as session:
        article = Article(
            mission_id=mission_id,
            target_keyword=target_keyword,
            title=title,
            html_content=html_content,
            faq_json_ld=faq_json_ld,
            meta_description=meta_description,
            word_count=word_count,
        )
        session.add(article)
        session.commit()
        return article.id


def fetch_article(article_id: int) -> Optional[dict]:
    """Fetch an article by ID."""
    with get_session() as session:
        article = session.get(Article, article_id)
        if not article:
            return None
        return {
            "id": article.id,
            "mission_id": article.mission_id,
            "target_keyword": article.target_keyword,
            "title": article.title,
            "html_content": article.html_content,
            "faq_json_ld": article.faq_json_ld,
            "meta_description": article.meta_description,
            "word_count": article.word_count,
            "created_at": article.created_at.isoformat() if article.created_at else None,
        }


def list_articles(mission_id: int) -> list[dict]:
    """List all articles for a mission."""
    with get_session() as session:
        stmt = select(Article).where(Article.mission_id == mission_id).order_by(Article.id.desc())
        return [
            {
                "id": a.id,
                "title": a.title,
                "target_keyword": a.target_keyword,
                "word_count": a.word_count,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in session.scalars(stmt).all()
        ]


# ============ PUBLISH LOG HELPERS ============


def save_publish_log(
    mission_id: int,
    article_id: int,
    wp_post_id: Optional[int] = None,
    wp_url: Optional[str] = None,
    status: str = "pending",
    error: Optional[str] = None,
) -> int:
    """Save a publish log entry and return its ID."""
    with get_session() as session:
        log = PublishLog(
            mission_id=mission_id,
            article_id=article_id,
            wp_post_id=wp_post_id,
            wp_url=wp_url,
            status=status,
            error=error,
        )
        session.add(log)
        session.commit()
        return log.id


def fetch_publish_log(log_id: int) -> Optional[dict]:
    """Fetch a publish log entry by ID."""
    with get_session() as session:
        log = session.get(PublishLog, log_id)
        if not log:
            return None
        return {
            "id": log.id,
            "mission_id": log.mission_id,
            "article_id": log.article_id,
            "wp_post_id": log.wp_post_id,
            "wp_url": log.wp_url,
            "status": log.status,
            "error": log.error,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }


def list_publish_logs(mission_id: int) -> list[dict]:
    """List all publish logs for a mission."""
    with get_session() as session:
        stmt = (
            select(PublishLog)
            .where(PublishLog.mission_id == mission_id)
            .order_by(PublishLog.id.desc())
        )
        return [
            {
                "id": log.id,
                "article_id": log.article_id,
                "wp_post_id": log.wp_post_id,
                "wp_url": log.wp_url,
                "status": log.status,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in session.scalars(stmt).all()
        ]
