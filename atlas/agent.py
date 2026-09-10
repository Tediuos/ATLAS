"""Persistent CLI and Python entry points for the Atlas LangGraph workflow."""

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from atlas import db
from atlas.journal import WriteJournal
from atlas.schemas import HarnessConfig
from atlas.workflow import build_graph, initial_state


def _paths():
    root = Path(os.getenv("ATLAS_STATE_DIR", "data"))
    root.mkdir(parents=True, exist_ok=True)
    return root / "checkpoints.db", root / "writes.db"


def _public_result(state, interrupts=()):
    result = {
        key: state.get(key)
        for key in (
            "mission_id",
            "summary",
            "status",
            "audit",
            "article",
            "keywords",
            "quality",
            "publish",
            "judgment",
            "linkedin_post",
            "linkedin_publish",
            "metrics",
            "events",
            "iterations",
            "tool_calls",
            "cache_hits",
            "errors",
        )
    }
    result["approvals"] = [item.value for item in interrupts]
    if interrupts:
        result["status"] = "awaiting_approval"
        result["summary"] = (
            "Review the destination, content, judge assessment and visibility before resuming"
        )
    return result


def run_mission(
    mission_text: str,
    max_iterations: int = 12,
    progress_callback=None,
    *,
    limits: HarnessConfig | None = None,
    model=None,
    services=None,
) -> dict:
    limits = limits or HarnessConfig(max_iterations=max_iterations)
    # Validate before creating a history row.
    initial_state(mission_text, 0, limits)
    url_match = re.search(r"https?://[^\s]+", mission_text)
    mission_id = db.save_mission(
        mission_text, url_match.group(0).rstrip(".,;") if url_match else ""
    )
    return _invoke(
        mission_id,
        initial_state(mission_text, mission_id, limits),
        model=model,
        services=services,
        progress_callback=progress_callback,
    )


def inspect_mission(mission_id: int) -> dict:
    checkpoints, _ = _paths()
    with SqliteSaver.from_conn_string(str(checkpoints)) as saver:
        graph = build_graph(checkpointer=saver, journal=None)
        snapshot = graph.get_state({"configurable": {"thread_id": str(mission_id)}})
        if not snapshot.values:
            raise ValueError("No checkpoint exists for this mission")
        interrupts = [i for task in snapshot.tasks for i in task.interrupts]
        return _public_result(snapshot.values, interrupts)


def resume_mission(
    mission_id: int,
    approved: bool,
    payload_hash: str,
    *,
    model=None,
    services=None,
    progress_callback=None,
) -> dict:
    from atlas.schemas import Approval

    decision = Approval(approved=approved, payload_hash=payload_hash)
    current = inspect_mission(mission_id)
    if current["status"] != "awaiting_approval":
        raise ValueError("Mission is not awaiting approval")
    if current["approvals"][0]["payload_hash"] != payload_hash:
        raise ValueError("Approval hash does not match the pending payload")
    return _invoke(
        mission_id,
        Command(resume=decision.model_dump()),
        model=model,
        services=services,
        progress_callback=progress_callback,
    )


def _invoke(mission_id, graph_input, *, model=None, services=None, progress_callback=None):
    checkpoints, writes = _paths()
    config = {"configurable": {"thread_id": str(mission_id)}, "recursion_limit": 250}
    with SqliteSaver.from_conn_string(str(checkpoints)) as saver:
        graph = build_graph(
            checkpointer=saver,
            journal=WriteJournal(writes),
            model=model,
            services=services,
            notify=progress_callback,
        )
        try:
            state = graph.invoke(graph_input, config)
        except Exception:
            db.update_mission(
                mission_id, status="failed", summary="Workflow interrupted by a runtime error"
            )
            raise
        result = _public_result(state, state.get("__interrupt__", ()))
    db.update_mission(
        mission_id,
        status=result["status"],
        summary=result["summary"],
        completed_at=None
        if result["status"] == "awaiting_approval"
        else datetime.now(timezone.utc),
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mission", nargs="?")
    parser.add_argument("--inspect", type=int, metavar="MISSION_ID")
    parser.add_argument("--resume", type=int, metavar="MISSION_ID")
    decisions = parser.add_mutually_exclusive_group()
    decisions.add_argument("--approve-hash")
    decisions.add_argument("--reject-hash")
    parser.add_argument("--max-iterations", type=int, default=12)
    args = parser.parse_args()
    if args.inspect:
        result = inspect_mission(args.inspect)
    elif args.resume and (args.approve_hash or args.reject_hash):
        result = resume_mission(
            args.resume, bool(args.approve_hash), args.approve_hash or args.reject_hash
        )
    elif args.mission:
        result = run_mission(args.mission, max_iterations=args.max_iterations)
    else:
        parser.error("Provide a mission, --inspect ID, or --resume ID with a decision hash")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 1 if result["status"] in {"failed", "budget_exceeded", "completed_with_errors"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
