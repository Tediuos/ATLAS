"""Wrapper Python pour Lighthouse CLI - extrait les Core Web Vitals + scores."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from atlas.network import validate_url


def run_lighthouse(url: str, mobile: bool = True, timeout: int = 120) -> dict:
    """
    Lance Lighthouse sur une URL et retourne un dict structuré.

    Args:
        url: URL à auditer
        mobile: True (défaut) pour audit mobile, False pour desktop
        timeout: timeout en secondes (Lighthouse peut être lent : 30-90s typique)
    """
    # Fichier temporaire pour la sortie JSON
    fd, output_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)  # on ferme le file descriptor, Lighthouse écrira dedans

    try:
        validate_url(url)
        executable = shutil.which("lighthouse")
        if not executable:
            return {"url": url, "ok": False, "error": "Lighthouse CLI is not installed"}
        command = [executable]
        if Path(executable).suffix.lower() in {".cmd", ".bat", ".ps1"}:
            # Invoke the JavaScript entry point directly on Windows; never use cmd.exe.
            entry = Path(executable).parent / "node_modules/lighthouse/cli/index.js"
            node = shutil.which("node")
            if not node or not entry.exists():
                return {
                    "url": url,
                    "ok": False,
                    "error": "Cannot locate Node/Lighthouse entry point",
                }
            command = [node, str(entry)]
        command.extend(
            [
                url,
                "--output=json",
                f"--output-path={output_path}",
                "--chrome-flags=--headless",
                "--quiet",
                "--no-enable-error-reporting",
            ]
        )
        if not mobile:
            command.append("--preset=desktop")
        result = subprocess.run(
            command, shell=False, capture_output=True, text=True, timeout=timeout
        )

        if not Path(output_path).exists() or Path(output_path).stat().st_size == 0:
            return {
                "url": url,
                "ok": False,
                "error": "Lighthouse n'a pas généré de sortie",
                "stderr": (result.stderr or "")[:500],
            }

        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)

        return _parse_lighthouse_output(data, url, mobile)

    except subprocess.TimeoutExpired:
        return {"url": url, "ok": False, "error": f"Timeout après {timeout}s"}
    except Exception as e:
        return {"url": url, "ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        try:
            os.unlink(output_path)
        except OSError:
            pass


# ============ PARSER ============


def _parse_lighthouse_output(data: dict, url: str, mobile: bool) -> dict:
    """Extrait uniquement les métriques utiles du JSON brut Lighthouse."""
    categories = data.get("categories", {})
    audits = data.get("audits", {})

    scores = {
        "performance": _score(categories.get("performance")),
        "seo": _score(categories.get("seo")),
        "accessibility": _score(categories.get("accessibility")),
        "best_practices": _score(categories.get("best-practices")),
    }

    metrics = {
        "lcp_ms": _audit_value(audits.get("largest-contentful-paint")),
        "cls": _audit_value(audits.get("cumulative-layout-shift")),
        "tbt_ms": _audit_value(audits.get("total-blocking-time")),
        "fcp_ms": _audit_value(audits.get("first-contentful-paint")),
        "si_ms": _audit_value(audits.get("speed-index")),
        "tti_ms": _audit_value(audits.get("interactive")),
    }

    # Opportunités = audits avec un gain de temps quantifié
    opportunities = []
    for audit_id, audit in audits.items():
        details = audit.get("details") or {}
        if (
            details.get("type") == "opportunity"
            and audit.get("score") is not None
            and audit["score"] < 1
        ):
            opportunities.append(
                {
                    "id": audit_id,
                    "title": audit.get("title"),
                    "description": (audit.get("description") or "")[:200],
                    "savings_ms": details.get("overallSavingsMs", 0),
                    "score": audit.get("score"),
                }
            )
    opportunities.sort(key=lambda x: x.get("savings_ms", 0), reverse=True)

    # Diagnostics : autres audits qui ont échoué (sans gain de temps quantifié)
    opp_ids = {o["id"] for o in opportunities}
    failed = []
    for audit_id, audit in audits.items():
        score = audit.get("score")
        if score is not None and score < 1 and audit_id not in opp_ids:
            failed.append(
                {
                    "id": audit_id,
                    "title": audit.get("title"),
                    "score": score,
                }
            )

    return {
        "url": url,
        "final_url": data.get("finalUrl", url),
        "ok": True,
        "form_factor": "mobile" if mobile else "desktop",
        "scores": scores,
        "metrics": metrics,
        "opportunities": opportunities[:10],
        "failed_audits_count": len(failed),
        "failed_audits_sample": failed[:10],
        "lighthouse_version": data.get("lighthouseVersion"),
    }


def _score(category):
    """Convertit un score Lighthouse 0-1 en 0-100."""
    if not category or category.get("score") is None:
        return None
    return round(category["score"] * 100)


def _audit_value(audit):
    """Récupère la valeur numérique d'un audit (ms ou autre)."""
    return audit.get("numericValue") if audit else None


# ============ MODE CLI ============

if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    print(f"Lighthouse audit: {target}")
    print("(comptez 30-60 secondes...)\n")
    result = run_lighthouse(target)
    print(json.dumps(result, indent=2, ensure_ascii=False))
