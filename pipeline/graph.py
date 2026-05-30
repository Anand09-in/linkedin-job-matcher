"""
LangGraph graph definition — wires all nodes into the pipeline.

Topology:

    START
      │
    scraper_node
      │
      ├──────────────────────┐
      ▼                      ▼
    jd_parser_node    resume_parser_node    ← parallel fan-out
      │                      │
      └──────────┬───────────┘
                 ▼
            matcher_node
                 │
                END

Usage:
    from pipeline.graph import build_graph
    graph = build_graph()
    result = graph.invoke({"resume_id": "abc-123"})

Phase 3.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from pipeline.nodes import (
    jd_parser_node,
    matcher_node,
    resume_parser_node,
    scraper_node,
)
from pipeline.state import PipelineState


def build_graph() -> StateGraph:
    """
    Build and compile the LangGraph pipeline.

    Returns a compiled graph ready to invoke.
    """
    graph = StateGraph(PipelineState)

    # ── Register nodes ────────────────────────────────────────────────────────
    graph.add_node("scraper", scraper_node)
    graph.add_node("jd_parser", jd_parser_node)
    graph.add_node("resume_parser", resume_parser_node)
    graph.add_node("matcher", matcher_node)

    # ── Wire edges ────────────────────────────────────────────────────────────
    # Entry point
    graph.add_edge(START, "scraper")

    # After scraping, jd_parser and resume_parser run in parallel
    graph.add_edge("scraper", "jd_parser")
    graph.add_edge("scraper", "resume_parser")

    # Both must complete before matcher runs
    graph.add_edge("jd_parser", "matcher")
    graph.add_edge("resume_parser", "matcher")

    # Matcher is the terminal node
    graph.add_edge("matcher", END)

    return graph.compile()


# ── Module-level compiled graph (imported by FastAPI routes) ──────────────────
# Compiled lazily so tests can import the module without triggering heavy imports
_graph_instance = None


def get_graph():
    """Return the cached compiled graph, building it on first call."""
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = build_graph()
    return _graph_instance


def run_pipeline(resume_id: str = "") -> dict:
    """
    Convenience wrapper — invoke the full pipeline and return final state.

    Args:
        resume_id: DB Resume.id to match against. If empty, uses active resume.

    Returns:
        Final PipelineState dict with scored_jobs, skill_gaps, errors.
    """
    from loguru import logger
    logger.info(f"[Pipeline] Starting run for resume_id={resume_id!r}")

    graph = get_graph()
    final_state = graph.invoke({"resume_id": resume_id, "errors": []})

    logger.info(
        f"[Pipeline] Complete — "
        f"jobs={len(final_state.get('scored_jobs', []))} | "
        f"errors={len(final_state.get('errors', []))}"
    )
    return final_state
