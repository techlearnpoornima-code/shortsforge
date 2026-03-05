"""
graph/pipeline.py
─────────────────
Assembles the LangGraph StateGraph with supervisor-based compliance.

Graph structure:
                    pick_universe
                         │
                    generate_content ◄──────────────┐
                         │                           │ (retry)
                         ▼                           │
                    compliance_check ────────────────┘
                         │
              ┌──────────┼──────────┬──────────┐
           pass       fix       learn        abort
              │          │          │
           (Send)   fix_content  update_rules
          /      \\      │          │
  gen_video  yt_meta   compliance_check ◄──┘
         │       │
         └───┬───┘
             ▼
       upload_youtube
             │
            END

HOW THE PARALLEL BRANCH WORKS
──────────────────────────────
LangGraph has two distinct mechanisms:

  1. Nodes      → return dict  (state update)
  2. Edge funcs → return str | list[Send]  (routing)

A function returning list[Send] MUST be used as an edge function,
never registered as a node. We wire this with two calls to
add_conditional_edges on the same source node:

  # Single call — no path_map dict — router returns str OR list[Send]:
  graph.add_conditional_edges("compliance_check", route_after_compliance)

route_after_compliance returns list[Send] on pass (parallel dispatch)
or a plain string ("fix_content" / "update_rules" / "abort") on fail.
Omitting the path_map dict is required when the router can return list[Send].
"""

from langgraph.graph import StateGraph, END

from graph.state import PipelineState
from graph.nodes import (
    pick_universe,
    generate_content,
    compliance_check,
    fix_content,
    update_compliance_rules,
    generate_video,
    build_youtube_meta,
    upload_youtube,
)
from graph.edges import (
    route_after_generate,
    route_after_compliance,
    route_after_fix,
    route_after_learning,
)


# ─────────────────────────────────────────────────────────────
#  Abort node
# ─────────────────────────────────────────────────────────────

def abort(state: PipelineState) -> dict:
    msg = (
        state.get("content_error")
        or state.get("fix_error")
        or f"Compliance failures: {state.get('compliance_failures', [])}"
    )
    print(f"\n🚫 [Node: abort] Pipeline aborted — {msg}")
    return {
        "pipeline_status": "failed",
        "error_message": msg,
    }


# Parallel dispatch is handled inside route_after_compliance (edges.py):
# it returns list[Send] on pass, a plain string on fail.


# ─────────────────────────────────────────────────────────────
#  Build the graph
# ─────────────────────────────────────────────────────────────

def build_pipeline() -> StateGraph:
    graph = StateGraph(PipelineState)

    # ── Register nodes ────────────────────────────────────────
    graph.add_node("pick_universe",      pick_universe)
    graph.add_node("generate_content",   generate_content)
    graph.add_node("compliance_check",   compliance_check)
    graph.add_node("fix_content",        fix_content)
    graph.add_node("update_rules",       update_compliance_rules)
    graph.add_node("generate_video",     generate_video)
    graph.add_node("build_youtube_meta", build_youtube_meta)
    graph.add_node("upload_youtube",     upload_youtube)
    graph.add_node("abort",              abort)

    # ── Entry point ───────────────────────────────────────────
    graph.set_entry_point("pick_universe")

    # ── Linear: pick_universe → generate_content ─────────────
    graph.add_edge("pick_universe", "generate_content")

    # ── Conditional: after content generation ────────────────
    graph.add_conditional_edges(
        "generate_content",
        route_after_generate,
        {
            "compliance_check": "compliance_check",
            "generate_content": "generate_content",
            "abort":            "abort",
        }
    )

    # ── Conditional: after compliance check ─────────────────────
    # route_after_compliance returns list[Send] on pass (parallel dispatch)
    # or a string on fail (fix_content / update_rules / abort).
    # No path_map dict — required when the router can return list[Send].
    graph.add_conditional_edges("compliance_check", route_after_compliance)

    # ── Conditional: after fix ────────────────────────────────
    graph.add_conditional_edges(
        "fix_content",
        route_after_fix,
        {
            "compliance_check": "compliance_check",
            "abort":            "abort",
        }
    )

    # ── Conditional: after learning ───────────────────────────
    graph.add_conditional_edges(
        "update_rules",
        route_after_learning,
        {
            "compliance_check": "compliance_check",
            "abort":            "abort",
        }
    )

    # ── Parallel branches converge at upload ─────────────────
    graph.add_edge("generate_video",     "upload_youtube")
    graph.add_edge("build_youtube_meta", "upload_youtube")

    # ── Terminal nodes ────────────────────────────────────────
    graph.add_edge("upload_youtube", END)
    graph.add_edge("abort",          END)

    return graph.compile()

