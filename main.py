"""
ShortsForge AI — LangGraph Pipeline
=====================================
Usage:
  python main.py                          # Run once
  python main.py --theme "office chaos"  # With theme hint
  python main.py --dry-run               # Skip YouTube upload
  python main.py --count 3              # Run 3 videos in sequence
  python main.py --schedule             # Post at 11:00 + 19:00 daily
  python main.py --visualise            # Print graph ASCII diagram and exit
"""

import os
import sys
import json
import time
import argparse
import schedule
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def print_banner():
    print("""
╔══════════════════════════════════════════════════════════╗
║        🎬  ShortsForge AI — LangGraph Edition  v2.0     ║
║   Conditional Branching + Parallel Video/Meta Pipeline   ║
║   Gemini 2.0 Flash → Veo 3 → YouTube Data API v3         ║
╚══════════════════════════════════════════════════════════╝
""")


def build_initial_state(theme: str, dry_run: bool) -> dict:
    """Construct the initial PipelineState for a new run."""
    return {
        "theme_hint": theme,
        "dry_run": dry_run,
        # Universe selection (filled by pick_universe node)
        "content_universe": None,
        "trend_context": None,
        "selected_character": None,
        "selected_scenario": None,
        # Content generation
        "content": None,
        "content_attempts": 0,
        "content_error": None,
        # Compliance — v3 supervisor fields
        "compliance_passed": False,
        "compliance_score": 0,
        "compliance_failures": [],
        "compliance_warnings": [],
        "compliance_suggestions": [],
        "trademark_issues": [],
        "supervisor_notes": "",
        "compliance_verdict": None,
        "compliance_fix_attempts": 0,
        # Learning & history
        "fix_history": [],
        "compliance_insights": None,
        "compliance_learning": None,
        "fix_error": None,
        # Video
        "video_path": None,
        "video_error": None,
        # Metadata
        "youtube_metadata": None,
        "meta_error": None,
        # Upload
        "video_id": None,
        "youtube_url": None,
        "upload_error": None,
        # Control
        "logs": [],
        "pipeline_status": "running",
        "error_message": None,
    }


def print_run_summary(final_state: dict, elapsed: float):
    status = final_state.get("pipeline_status", "unknown")
    icon = "✅" if status == "success" else "❌"

    print(f"\n{'━' * 60}")
    print(f"  {icon}  Pipeline finished in {elapsed:.1f}s  —  {status.upper()}")

    if status == "success":
        concept = final_state.get("content", {}).get("concept", {})
        print(f"  {concept.get('emoji', '')} {concept.get('title', '')}")
        print(f"  📺  {final_state.get('youtube_url', '')}")
        print(f"  🔖  {final_state.get('youtube_metadata', {}).get('best_hashtag', '')}")
        print(f"  📊  Compliance score: {final_state.get('compliance_score', 0)}/100")
    else:
        print(f"  ✗  {final_state.get('error_message', 'Unknown error')}")

    print(f"\n  📋  Log ({len(final_state.get('logs', []))} entries):")
    for entry in final_state.get("logs", []):
        print(f"      {entry}")
    print(f"{'━' * 60}\n")

    # Persist to log file
    log_path = Path("output/pipeline_log.json")
    log_path.parent.mkdir(exist_ok=True)
    history = json.loads(log_path.read_text()) if log_path.exists() else []
    history.append({
        "run_id": len(history) + 1,
        "timestamp": datetime.utcnow().isoformat(),
        "status": status,
        "concept": (final_state.get("content") or {}).get("concept", {}).get("title"),
        "emoji":  (final_state.get("content") or {}).get("concept", {}).get("emoji"),
        "compliance_score": final_state.get("compliance_score"),
        "youtube_url": final_state.get("youtube_url"),
        "video_path": final_state.get("video_path"),
        "elapsed_seconds": round(elapsed, 1),
        "dry_run": final_state.get("dry_run"),
        "logs": final_state.get("logs", []),
    })
    log_path.write_text(json.dumps(history, indent=2))
    print(f"  📁  Run logged to {log_path}")


def run_once(pipeline, theme: str, dry_run: bool):
    """Execute one full pipeline run."""
    initial_state = build_initial_state(theme=theme, dry_run=dry_run)
    start = time.time()

    print(f"\n{'━' * 60}")
    print(f"  🚀  Starting pipeline — {datetime.now().strftime('%H:%M:%S')}")
    if theme:
        print(f"  🎯  Theme hint: {theme}")
    if dry_run:
        print(f"  ⚠️   Dry run mode — YouTube upload skipped")
    print(f"{'━' * 60}")

    final_state = pipeline.invoke(initial_state)
    elapsed = time.time() - start
    print_run_summary(final_state, elapsed)
    return final_state


def main():
    parser = argparse.ArgumentParser(description="ShortsForge AI — LangGraph Pipeline")
    parser.add_argument("--theme",      type=str, default="", help="Theme hint for content")
    parser.add_argument("--dry-run",    action="store_true",  help="Skip YouTube upload")
    parser.add_argument("--count",      type=int, default=1,  help="Videos to generate per run")
    parser.add_argument("--schedule",   action="store_true",  help="Run on daily schedule")
    parser.add_argument("--visualise",  action="store_true",  help="Print graph diagram and exit")
    args = parser.parse_args()

    print_banner()

    # Validate keys early
    if not os.getenv("GOOGLE_API_KEY"):
        print("❌ GOOGLE_API_KEY not set in .env"); sys.exit(1)
    else:
        print("✅ GOOGLE_API_KEY set in .env")

    dry_run = args.dry_run or os.getenv("DRY_RUN", "false").lower() == "true"

    # Build the graph (compile once, reuse across scheduled runs)
    from graph.pipeline import build_pipeline
    pipeline = build_pipeline()

    if args.visualise:
        print("📊 Graph structure:")
        print(pipeline.get_graph().draw_ascii())
        return

    def run_batch():
        for i in range(args.count):
            if args.count > 1:
                print(f"\n📦 Video {i+1} of {args.count}")
            try:
                run_once(pipeline, theme=args.theme, dry_run=dry_run)
            except Exception as e:
                import traceback
                print(f"\n❌ Unhandled error: {e}")
                traceback.print_exc()

    if args.schedule:
        post_times = os.getenv("POST_TIMES", "11:00,19:00").split(",")
        print(f"📅 Scheduler active — posting at: {', '.join(t.strip() for t in post_times)}")
        print("   Press Ctrl+C to stop.\n")
        for t in post_times:
            schedule.every().day.at(t.strip()).do(run_batch)
        run_batch()  # Run immediately on start
        while True:
            schedule.run_pending()
            time.sleep(30)
    else:
        run_batch()


if __name__ == "__main__":
    main()
