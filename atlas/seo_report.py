"""Generate HTML and PDF SEO reports from Atlas mission results using Jinja2."""
from datetime import datetime
from pathlib import Path
from typing import Optional

from jinja2 import BaseLoader, Environment


_REPORT_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Atlas SEO Report — {{ url }}</title>
<style>
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;padding:20px;color:#1a1a1a;background:#f8f9fa}
  .wrap{max-width:1000px;margin:0 auto;background:#fff;padding:40px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.1)}
  h1{font-size:2em;margin-bottom:4px}
  h2{color:#333;border-bottom:2px solid #e0e0e0;padding-bottom:8px;margin-top:40px}
  .meta{color:#666;font-size:.9em;margin-bottom:32px}
  .badge{display:inline-block;padding:8px 20px;border-radius:50px;font-size:2em;font-weight:700;color:#fff}
  .good{background:#22c55e}.medium{background:#f59e0b}.poor{background:#ef4444}
  .score-card{text-align:center;padding:24px;background:#f8f9fa;border-radius:8px;margin:20px 0}
  table{width:100%;border-collapse:collapse}
  th{background:#f3f4f6;padding:10px 12px;text-align:left;font-size:.85em;color:#555;text-transform:uppercase;letter-spacing:.05em}
  td{padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:.9em}
  tr:hover{background:#f9fafb}
  .p1,.p2,.p3{color:#dc2626;font-weight:700}
  .p4,.p5,.p6{color:#d97706;font-weight:700}
  .p7,.p8,.p9,.p10{color:#65a30d;font-weight:700}
  .el{background:#dcfce7;color:#166534;padding:2px 8px;border-radius:4px;font-size:.8em}
  .em{background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;font-size:.8em}
  .eh{background:#fee2e2;color:#991b1b;padding:2px 8px;border-radius:4px;font-size:.8em}
  .ii{color:#2563eb}.ic{color:#7c3aed}.it{color:#059669}
  .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin:16px 0}
  .mc{background:#f8f9fa;padding:16px;border-radius:8px;text-align:center}
  .mv{font-size:1.8em;font-weight:700;color:#4f46e5}
  .ml{font-size:.8em;color:#666;margin-top:4px}
  .prev{background:#f8f9fa;padding:20px;border-radius:8px;border-left:4px solid #6366f1;margin:16px 0;max-height:400px;overflow:hidden}
  .sp{display:inline-block;padding:4px 12px;border-radius:4px;font-size:.9em}
  .spub{background:#dcfce7;color:#166534}.sdr{background:#e0e7ff;color:#3730a3}.sfail{background:#fee2e2;color:#991b1b}
  .footer{text-align:center;margin-top:48px;color:#9ca3af;font-size:.85em;border-top:1px solid #e5e7eb;padding-top:24px}
</style>
</head>
<body>
<div class="wrap">
  <h1>Atlas SEO Report</h1>
  <div class="meta">Generated {{ generated_at }} &bull; <a href="{{ url }}" target="_blank">{{ url }}</a></div>

  {% if audit %}
  <h2>Audit Score</h2>
  {% set s = audit.score | default(0) | int %}
  <div class="score-card">
    <div class="badge {{ 'good' if s >= 70 else ('medium' if s >= 50 else 'poor') }}">{{ s }}/100</div>
    <p style="color:#666;margin-top:12px">Overall SEO Health Score</p>
  </div>

  {% if audit.lighthouse and audit.lighthouse.scores %}
  <div class="grid">
    {% for key, label in [('seo','Lighthouse SEO'),('performance','Performance'),('accessibility','Accessibility'),('best_practices','Best Practices')] %}
    {% set v = audit.lighthouse.scores.get(key) %}
    <div class="mc"><div class="mv">{{ v if v is not none else 'N/A' }}</div><div class="ml">{{ label }}</div></div>
    {% endfor %}
  </div>
  {% endif %}

  <h2>Top SEO Issues</h2>
  {% if audit.top_issues %}
  <table>
    <thead><tr><th>#</th><th>Category</th><th>Issue</th><th>Recommendation</th><th>Effort</th></tr></thead>
    <tbody>
    {% for issue in audit.top_issues %}
    <tr>
      <td class="p{{ issue.priority }}">{{ issue.priority }}</td>
      <td>{{ issue.category | title }}</td>
      <td><strong>{{ issue.issue }}</strong><br><small style="color:#666">{{ issue.impact }}</small></td>
      <td>{{ issue.recommendation }}</td>
      <td><span class="e{{ issue.effort[0] }}">{{ issue.effort | title }}</span></td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<p style="color:#666">No issues data available.</p>{% endif %}
  {% endif %}

  {% if keywords %}
  <h2>Keyword Strategy</h2>
  <p><strong>{{ keywords | length }}</strong> keywords across <strong>{{ cluster_count }}</strong> clusters.</p>
  <table>
    <thead><tr><th>Keyword</th><th>Cluster</th><th>Intent</th><th>Volume Rank</th></tr></thead>
    <tbody>
    {% for kw in keywords[:20] %}
    <tr>
      <td><strong>{{ kw.keyword }}</strong></td>
      <td>{{ kw.cluster | replace('_',' ') | title }}</td>
      <td><span class="i{{ kw.intent[0] }}">{{ kw.intent | title }}</span></td>
      <td>{{ kw.volume_rank }}/10</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  {% endif %}

  {% if article %}
  <h2>Article Preview</h2>
  <p><strong>Title:</strong> {{ article.title }}</p>
  <p><strong>Keyword:</strong> {{ article.target_keyword }} &bull; <strong>Words:</strong> {{ article.word_count }}</p>
  <p><strong>Meta:</strong> {{ article.meta_description }}</p>
  <div class="prev">
    {{ article.html_content[:2000] | safe }}
    {% if article.html_content | length > 2000 %}<p><em>… (truncated)</em></p>{% endif %}
  </div>
  {% endif %}

  {% if publish %}
  <h2>Publish Status</h2>
  {% if publish.ok %}
  <p>
    <span class="sp spub">{{ publish.status | title }}</span>
    &nbsp; Post #<strong>{{ publish.post_id }}</strong>
    &nbsp; <a href="{{ publish.link }}" target="_blank">View Post →</a>
  </p>
  {% else %}
  <p><span class="sp sfail">Failed</span> {{ publish.error }}</p>
  {% endif %}
  {% endif %}

  <div class="footer">Generated by <strong>Atlas SEO Agent</strong> &bull; {{ generated_at }}</div>
</div>
</body>
</html>
"""


def generate_report(
    audit: Optional[dict] = None,
    keywords: Optional[list] = None,
    article: Optional[dict] = None,
    publish: Optional[dict] = None,
    output_path: Optional[str] = None,
) -> str:
    """
    Render an HTML SEO report from mission result data.

    Args:
        audit: Audit result dict from run_audit() — provides score and issues.
        keywords: Ranked keyword list from research_keywords().
        article: Article dict from write_article().
        publish: Publish result dict from publish_to_wordpress().
        output_path: Optional file path to save the HTML report to disk.

    Returns:
        Rendered HTML string.
    """
    env = Environment(loader=BaseLoader(), autoescape=False)
    template = env.from_string(_REPORT_TEMPLATE)

    url = (audit or {}).get("url", "N/A")
    cluster_count = len(set((kw.get("cluster", "") for kw in (keywords or []))))

    html = template.render(
        url=url,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        audit=audit,
        keywords=keywords or [],
        cluster_count=cluster_count,
        article=article,
        publish=publish,
    )

    if output_path:
        Path(output_path).write_text(html, encoding="utf-8")

    return html


def generate_pdf_report(
    audit: Optional[dict] = None,
    keywords: Optional[list] = None,
    article: Optional[dict] = None,
    publish: Optional[dict] = None,
    output_path: str = "seo_report.pdf",
) -> bytes:
    """
    Render and save a PDF SEO report using WeasyPrint.

    WeasyPrint must be installed separately (it requires system libraries).
    Install with: pip install weasyprint

    Args:
        audit: Audit result dict.
        keywords: Keyword list.
        article: Article dict.
        publish: Publish result dict.
        output_path: Destination PDF file path.

    Returns:
        Raw PDF bytes.

    Raises:
        RuntimeError: If WeasyPrint is not installed or PDF generation fails.
    """
    html_content = generate_report(audit=audit, keywords=keywords, article=article, publish=publish)
    try:
        from weasyprint import HTML  # type: ignore

        pdf_bytes = HTML(string=html_content).write_pdf()
        Path(output_path).write_bytes(pdf_bytes)
        return pdf_bytes
    except ImportError as exc:
        raise RuntimeError("WeasyPrint not installed. Run: pip install weasyprint") from exc
    except Exception as exc:
        raise RuntimeError(f"PDF generation failed: {exc}") from exc
