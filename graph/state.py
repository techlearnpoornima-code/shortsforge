"""
graph/state.py
──────────────
The single shared state object that every LangGraph node reads from and writes to.
Uses TypedDict so LangGraph can merge partial updates from parallel branches.
v3: Adds supervisor-based compliance tracking and learning capabilities.
"""

from typing import TypedDict, Optional, Annotated, List, Dict, Any
import operator


class PipelineState(TypedDict):
    # ── Input ────────────────────────────────────────────────
    theme_hint: str                      # Optional user-provided theme override
    dry_run: bool                        # Skip real YouTube upload if True

    # ── Universe & Trend Selection ────────────────────────────
    content_universe: Optional[str]      # e.g. "pop_culture", "animals_human_problems"
    trend_context: Optional[str]         # What Gemini found trending today
    selected_character: Optional[str]    # Character picked for this video
    selected_scenario: Optional[str]     # Scenario picked for this video

    # ── Agent 1: Content Generation ──────────────────────────
    content: Optional[Dict[str, Any]]    # Full Gemini-generated content package
    content_attempts: int                 # How many times we've tried generating
    content_error: Optional[str]          # Last generation error message

    # ── Supervisor Compliance (NEW) ───────────────────────────
    compliance_passed: bool                # Gate: did content pass all checks?
    compliance_score: int                  # 0–100 from supervisor
    compliance_failures: List[str]         # Formatted failure messages
    compliance_warnings: List[str]         # Non-blocking warnings
    compliance_suggestions: List[str]      # Improvement suggestions from supervisor
    trademark_issues: List[str]            # Specific trademark violations found
    supervisor_notes: str                  # Brief explanation of verdict
    compliance_verdict: Optional[Dict[str, Any]]  # Full structured verdict
    compliance_fix_attempts: int            # How many fix attempts made
    
    # ── Learning & History (NEW) ──────────────────────────────
    fix_history: List[Dict[str, Any]]      # History of fix attempts for learning
    compliance_insights: Optional[Dict[str, Any]]  # Patterns learned from failures
    compliance_learning: Optional[Dict[str, Any]]  # Latest learning results
    fix_error: Optional[str]                # Error during fix attempt

    # ── Parallel Branch A: Video Generation ──────────────────
    video_path: Optional[str]              # Local path to generated .mp4
    video_error: Optional[str]

    # ── Parallel Branch B: YouTube Metadata ──────────────────
    youtube_metadata: Optional[Dict[str, Any]]   # Finalised upload-ready metadata
    meta_error: Optional[str]

    # ── Agent 3: YouTube Upload ───────────────────────────────
    video_id: Optional[str]
    youtube_url: Optional[str]
    upload_error: Optional[str]

    # ── Pipeline control ─────────────────────────────────────
    # Annotated with operator.add so parallel branches can both append logs
    logs: Annotated[List[str], operator.add]
    pipeline_status: str                    # "running" | "success" | "failed"
    error_message: Optional[str]            # Final error if pipeline aborts