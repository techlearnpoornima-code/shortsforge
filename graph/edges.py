"""
graph/edges.py
──────────────
Conditional edge functions.

Edge map:
  after_generate_content  → "compliance_check" | "generate_content" | "abort"
  after_compliance_check  → list[Send] (parallel) | "fix_content" | "update_rules" | "abort"
  after_fix_content       → "compliance_check" | "abort"
  after_update_rules      → "compliance_check" | "abort"

HOW THE PARALLEL BRANCH WORKS
──────────────────────────────
LangGraph add_conditional_edges supports two modes:

  Mode A (with path_map dict): router returns str → mapped to node name
  Mode B (no path_map):        router returns str | list[Send] → used directly

We use Mode B for compliance_check so route_after_compliance can return
either a plain string (fix/learn/abort) or list[Send] (parallel dispatch).
In pipeline.py this is wired WITHOUT a path_map dict:

    graph.add_conditional_edges("compliance_check", route_after_compliance)
"""

from langgraph.constants import Send
from graph.state import PipelineState

MAX_CONTENT_ATTEMPTS = 3
MAX_FIX_ATTEMPTS = 2
LEARNING_THRESHOLD = 2  # Must be <= MAX_FIX_ATTEMPTS so update_rules is reachable


def route_after_generate(state: PipelineState) -> str:
    """
    After generate_content:
      - If content was generated → compliance_check
      - If failed but retries remain → regenerate (back to generate_content)
      - If out of retries → abort
    """
    if state.get("content") is not None:
        return "compliance_check"

    attempts = state.get("content_attempts", 0)
    if attempts < MAX_CONTENT_ATTEMPTS:
        print(f"   ↩️  Retrying content generation (attempt {attempts}/{MAX_CONTENT_ATTEMPTS})")
        return "generate_content"

    print(f"   ✗ Content generation failed after {MAX_CONTENT_ATTEMPTS} attempts — aborting")
    return "abort"


def route_after_compliance(state: PipelineState):
    """
    After compliance_check:
      - Passed  → returns list[Send] to dispatch generate_video + build_youtube_meta in parallel
      - Failed + fix retries remain → returns "fix_content"
      - Failed + out of retries + enough history → returns "update_rules"
      - Failed + out of options → returns "abort"

    Returns str | list[Send].  Must be used WITHOUT a path_map dict in
    add_conditional_edges so LangGraph accepts the list[Send] return value.
    """
    if state.get("compliance_passed"):
        print("   ✅ Compliance passed — dispatching parallel video+meta generation")
        return [
            Send("generate_video",     state),
            Send("build_youtube_meta", state),
        ]

    fix_attempts = state.get("compliance_fix_attempts", 0)

    if fix_attempts < MAX_FIX_ATTEMPTS:
        print(f"   🔧 Routing to fix_content (fix attempt {fix_attempts + 1}/{MAX_FIX_ATTEMPTS})")
        return "fix_content"

    fix_history = state.get("fix_history", [])
    if len(fix_history) >= LEARNING_THRESHOLD and not state.get("compliance_insights"):
        print(f"   📚 Multiple failures detected — triggering learning node")
        return "update_rules"

    failures = state.get("compliance_failures", [])
    print(f"   ✗ Compliance failed after {MAX_FIX_ATTEMPTS} fix attempts — aborting")
    if failures:
        print(f"   Failures: {failures[:3]}" + ("..." if len(failures) > 3 else ""))
    return "abort"


def route_after_fix(state: PipelineState) -> str:
    """
    After fix_content:
      - Always go back to compliance_check for re-evaluation
      - But first check if we need to abort due to critical errors
    """
    if state.get("fix_error"):
        print(f"   ✗ Fix attempt failed with error — aborting")
        return "abort"
    
    fix_attempts = state.get("compliance_fix_attempts", 0)
    print(f"   ↩️  Returning to compliance_check after fix attempt {fix_attempts}")
    return "compliance_check"


def route_after_learning(state: PipelineState) -> str:
    """
    After update_compliance_rules:
      - compliance_insights set ("completed") → insights loaded, retry compliance
      - anything else (None or error string)  → abort
    """
    learning_status = state.get("compliance_learning")
    if learning_status == "completed":
        print(f"   📚 Learning completed — returning to compliance_check with new insights")
        return "compliance_check"

    print(f"   ✗ Learning failed — aborting pipeline")
    return "abort"

