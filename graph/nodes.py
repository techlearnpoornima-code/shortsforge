"""
graph/nodes.py  (v2 — Gemini Edition)
──────────────────────────────────────
All LangGraph nodes. Every node is a pure function:
  (PipelineState) -> dict  (partial state update)

Nodes:
  0. pick_universe        — Gemini picks universe + character + scenario (trend-aware)
  1. generate_content     — Gemini generates full content package
  2. compliance_check     — Rule-based gate + trademark scan
  3. fix_content          — Gemini fixes compliance failures
  4. generate_video       — Veo 3 generates 8-sec animated Short  [parallel A]
  5. build_youtube_meta   — Validates + enriches YT metadata       [parallel B]
  6. upload_youtube       — Uploads + pins comment
"""


import os
import re
import json
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from google import genai
from google.genai import types

from graph.state import PipelineState
from graph.universes import (
    UNIVERSES,
    select_universe,
    get_available_scenarios,
    get_available_characters,
    mark_used,
    get_used_context,
)
from graph.compliance_supervisor import ComplianceSupervisor, ComplianceVerdict
from graph.parser import _parse_json

# ─────────────────────────────────────────────────────────────
#  Shared Google GenAI client  (Gemini + Veo, single key)
# ─────────────────────────────────────────────────────────────

_genai_client: genai.Client | None = None

def _client() -> genai.Client:
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    return _genai_client


GEMINI_MODEL = "models/gemini-2.5-flash"


def _gemini(prompt: str, system: str = "", temperature: float = 0.9) -> str:
    """Call Gemini — raw text. Use _gemini_json() for structured output."""
    if system:
        full_prompt = f"SYSTEM INSTRUCTIONS:\n{system}\n\nUSER REQUEST:\n{prompt}"
    else:
        full_prompt = prompt
    response = _client().models.generate_content(
        model=GEMINI_MODEL,
        contents=[types.Content(role="user", parts=[types.Part(text=full_prompt)])],
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=4096,
        )
    )
    return response.text.strip()


def _gemini_json(
    prompt: str,
    schema: types.Schema,
    system: str = "",
    temperature: float = 0.9,
) -> dict:
    """
    Call Gemini with response_schema — forces constrained JSON decoding.
    The model CANNOT produce markdown fences, truncated objects, or
    missing fields. Eliminates all JSON parse errors.
    max_output_tokens=8192 covers the largest output (generate_content
    with 250-word veo_prompt + script + metadata ≈ 3000 tokens).
    """
    if system:
        full_prompt = f"SYSTEM INSTRUCTIONS:\n{system}\n\nUSER REQUEST:\n{prompt}"
    else:
        full_prompt = prompt
    response = _client().models.generate_content(
        model=GEMINI_MODEL,
        contents=[types.Content(role="user", parts=[types.Part(text=full_prompt)])],
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=8192,
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    if hasattr(response, "parsed") and response.parsed is not None:
        return response.parsed
    if response.text:
        return json.loads(response.text)
    finish = getattr(response, "finish_reason", "unknown")
    raise ValueError(f"Empty Gemini response — finish_reason={finish}")


# ─────────────────────────────────────────────────────────────
#  Response schemas — one per node. Built once at module load.
# ─────────────────────────────────────────────────────────────

# NODE 0 — pick_universe
SCHEMA_PICK_UNIVERSE = types.Schema(
    type=types.Type.OBJECT,
    required=["universe_key", "reasoning", "character", "character_tag",
              "scenario", "scenario_tag", "trend_context"],
    properties={
        "universe_key":  types.Schema(type=types.Type.STRING),
        "reasoning":     types.Schema(type=types.Type.STRING),
        "character":     types.Schema(type=types.Type.STRING),
        "character_tag": types.Schema(type=types.Type.STRING),
        "scenario":      types.Schema(type=types.Type.STRING),
        "scenario_tag":  types.Schema(type=types.Type.STRING),
        "trend_context": types.Schema(type=types.Type.STRING),
    },
)

# NODE 1 & 3 — generate_content / fix_content (identical output shape)
_SCRIPT_LINE = types.Schema(
    type=types.Type.OBJECT,
    required=["timestamp", "speaker", "dialogue", "action"],
    properties={
        "timestamp": types.Schema(type=types.Type.STRING),
        "speaker":   types.Schema(type=types.Type.STRING),
        "dialogue":  types.Schema(type=types.Type.STRING),
        "action":    types.Schema(type=types.Type.STRING),
    },
)
SCHEMA_CONTENT_PACKAGE = types.Schema(
    type=types.Type.OBJECT,
    required=["concept", "script", "veo_prompt",
              "youtube_metadata", "engagement", "compliance"],
    properties={
        "concept": types.Schema(
            type=types.Type.OBJECT,
            required=["title", "universe", "character", "emoji",
                      "strategy", "hook_description", "scenario_tags"],
            properties={
                "title":            types.Schema(type=types.Type.STRING),
                "universe":         types.Schema(type=types.Type.STRING),
                "character":        types.Schema(type=types.Type.STRING),
                "emoji":            types.Schema(type=types.Type.STRING),
                "strategy":         types.Schema(type=types.Type.STRING),
                "hook_description": types.Schema(type=types.Type.STRING),
                "scenario_tags":    types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(type=types.Type.STRING)),
            },
        ),
        "script": types.Schema(
            type=types.Type.OBJECT,
            required=["lines", "loop_note"],
            properties={
                "lines":     types.Schema(
                    type=types.Type.ARRAY, items=_SCRIPT_LINE),
                "loop_note": types.Schema(type=types.Type.STRING),
            },
        ),
        "veo_prompt": types.Schema(
            type=types.Type.OBJECT,
            required=["main_prompt", "style", "duration",
                      "aspect_ratio", "audio_description"],
            properties={
                "main_prompt":       types.Schema(type=types.Type.STRING),
                "style":             types.Schema(type=types.Type.STRING),
                "duration":          types.Schema(type=types.Type.STRING),
                "aspect_ratio":      types.Schema(type=types.Type.STRING),
                "audio_description": types.Schema(type=types.Type.STRING),
            },
        ),
        "youtube_metadata": types.Schema(
            type=types.Type.OBJECT,
            required=["title", "description", "tags", "best_hashtag",
                      "category_id", "made_for_kids", "thumbnail_moment"],
            properties={
                "title":            types.Schema(type=types.Type.STRING),
                "description":      types.Schema(type=types.Type.STRING),
                "tags":             types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(type=types.Type.STRING)),
                "best_hashtag":     types.Schema(type=types.Type.STRING),
                "category_id":      types.Schema(type=types.Type.STRING),
                "made_for_kids":    types.Schema(type=types.Type.BOOLEAN),
                "thumbnail_moment": types.Schema(type=types.Type.STRING),
            },
        ),
        "engagement": types.Schema(
            type=types.Type.OBJECT,
            required=["pinned_comment", "ab_title_variant"],
            properties={
                "pinned_comment":   types.Schema(type=types.Type.STRING),
                "ab_title_variant": types.Schema(type=types.Type.STRING),
            },
        ),
        "compliance": types.Schema(
            type=types.Type.OBJECT,
            required=["copyright_clear", "family_friendly", "no_real_people_named",
                      "parody_safe", "original_concept", "has_3sec_hook",
                      "is_loopable", "has_cta_overlay", "score"],
            properties={
                "copyright_clear":      types.Schema(type=types.Type.BOOLEAN),
                "family_friendly":      types.Schema(type=types.Type.BOOLEAN),
                "no_real_people_named": types.Schema(type=types.Type.BOOLEAN),
                "parody_safe":          types.Schema(type=types.Type.BOOLEAN),
                "original_concept":     types.Schema(type=types.Type.BOOLEAN),
                "has_3sec_hook":        types.Schema(type=types.Type.BOOLEAN),
                "is_loopable":          types.Schema(type=types.Type.BOOLEAN),
                "has_cta_overlay":      types.Schema(type=types.Type.BOOLEAN),
                "score":                types.Schema(type=types.Type.INTEGER),
            },
        ),
    },
)

# NODE 3.5 — update_compliance_rules
SCHEMA_LEARNING = types.Schema(
    type=types.Type.OBJECT,
    required=["patterns", "suggested_rules", "new_blacklist_entries",
              "problematic_universes", "learning_summary"],
    properties={
        "patterns":              types.Schema(
            type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
        "suggested_rules":       types.Schema(
            type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
        "new_blacklist_entries": types.Schema(
            type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
        "problematic_universes": types.Schema(
            type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
        "learning_summary":      types.Schema(type=types.Type.STRING),
    },
)


# ─────────────────────────────────────────────────────────────
#  NODE 0 — Pick Universe  (trend-aware AI selection)
# ─────────────────────────────────────────────────────────────

TREND_PICKER_PROMPT = """You are a YouTube Shorts content strategist picking content for a MASS GLOBAL AUDIENCE.

YOUR AUDIENCE: Everyday people aged 13-45, scrolling their phone, half-paying attention.
They will NOT get niche jokes. They DO laugh at: physical comedy, relatable frustration, fish-out-of-water, universal embarrassment.

Available content universes (pick based on weight guidance):
{universe_list}

UNIVERSE SELECTION RULES — follow these strictly:
- animals_human_problems: HIGHEST priority — universal appeal, zero cultural knowledge needed
- sports_athletes: HIGH priority — pick globally famous sports (cricket, football/soccer, athletics)
  → MUST pick characters from cricket or football first, NOT basketball (too US-centric)
  → GOOD: Indian cricket star trying Kathak dance. BAD: basketball player doing science.
- pop_culture: MEDIUM priority — only pick when scenario is visually obvious without explanation
- office_workplace: MEDIUM priority — great for Monday/email/meeting relatable content
- historical_figures: LOW priority — ONLY pick if scenario requires zero historical knowledge
  → GOOD: Napoleon confused by a revolving door. BAD: Einstein solving hip-hop physics equations.
  → The joke must work even if the viewer has NEVER heard of the character.

WHAT MAKES CONTENT FAIL (avoid these):
- Clever wordplay or puns that need thinking
- Niche knowledge (sports statistics, historical facts, science concepts)
- Abstract situations (cryptocurrency, existential dread, complex emotions)
- US-only cultural references (American football, baseball, specific US celebs)

WHAT MAKES CONTENT SUCCEED (aim for these):
- Instantly visual: you can describe the joke in one sentence with no context
- Universal frustration: everyone has experienced this embarrassment
- Physical comedy: the character's body/reaction IS the joke
- Surprise contrast: the mismatch is obvious within 1 second

Scenarios used recently — DO NOT repeat:
{recent_scenarios}

Characters used recently — avoid repeating these tags:
{recent_characters}

Universes used recently — avoid same universe 3x in a row:
{recent_universes}

Titles used recently — avoid similar names:
{recent_titles}

User theme hint (can be empty): "{theme_hint}"

Your task:
1. Pick the universe following the priority rules above
2. Pick a character that a global audience of any age will immediately recognise
3. Pick the SIMPLEST, most VISUAL scenario — if you need more than one sentence to explain why it is funny, it is too complex
4. The comedy must be obvious in the first 2 seconds — no setup required

Return ONLY this JSON (no markdown fences):
{{
  "universe_key": "pop_culture|sports_athletes|historical_figures|animals_human_problems|office_workplace",
  "reasoning": "Why this is instantly funny to a 13-year-old with no context (one sentence)",
  "character": "Full parody-safe character description to use",
  "character_tag": "short_tag_from_pool",
  "scenario": "The scenario string",
  "scenario_tag": "three_word_slug",
  "trend_context": "Simple relatable hook — max 15 words, no niche references"
}}"""



def pick_universe(state: PipelineState) -> dict:
    """Gemini picks the best universe + character + scenario based on today's trends."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n🎯 [Node: pick_universe] Selecting today's content...")

    try:
        used = get_used_context()
        now = datetime.now()

        universe_list = "\n".join(
            f"  {k}: {v['name']} — {v['description']}"
            for k, v in UNIVERSES.items()
        )

        prompt = TREND_PICKER_PROMPT.format(
            year=now.year,
            month=now.strftime("%B"),
            universe_list=universe_list,
            recent_scenarios=json.dumps(used["recent_scenarios"][-15:]),
            recent_characters=json.dumps(used["recent_characters"][-15:]),
            recent_universes=json.dumps(used["recent_universes"]),
            recent_titles=json.dumps(used["recent_titles"][-10:]),
            theme_hint=state.get("theme_hint", ""),
        )

        sel = _gemini_json(prompt, schema=SCHEMA_PICK_UNIVERSE)

        universe_key = sel["universe_key"]
        print(f"   ✓ Universe:   {UNIVERSES[universe_key]['emoji']} {UNIVERSES[universe_key]['name']}")
        print(f"   ✓ Character:  {sel['character']}")
        print(f"   ✓ Scenario:   {sel['scenario']}")
        print(f"   ✓ Trend hook: {sel['trend_context']}")

        return {
            "content_universe": universe_key,
            "selected_character": sel["character"],
            "selected_scenario": sel["scenario"],
            "trend_context": sel["trend_context"],
            "logs": [f"[{ts}] pick_universe: ✓ {universe_key} — {sel['trend_context']}"],
        }

    except Exception as e:
        # Graceful fallback — random selection
        print(f"   ⚠️  Gemini pick failed ({e}), using random fallback")
        universe = select_universe(force=state.get("theme_hint", ""))
        chars     = get_available_characters(universe["key"])
        scenarios = get_available_scenarios(universe["key"])
        char      = random.choice(chars)
        scenario  = random.choice(scenarios)

        return {
            "content_universe": universe["key"],
            "selected_character": char["name"],
            "selected_scenario": scenario,
            "trend_context": "evergreen comedy",
            "logs": [f"[{ts}] pick_universe: ⚠️ random fallback — {universe['key']}"],
        }


# ─────────────────────────────────────────────────────────────
#  NODE 1 — Generate Content
# ─────────────────────────────────────────────────────────────

CONTENT_SYSTEM = """You are ShortsForge AI — viral YouTube Shorts writer for a MASS GLOBAL AUDIENCE in 2026.

YOUR AUDIENCE: Everyday people aged 13-45, any country, scrolling phone, half-paying attention.
COMEDY LEVEL: Physical, visual, relatable. Like a cartoon punchline — no explanation needed.
NOT your audience: film critics, sports analysts, history professors.

CONTENT RULES — violation = rejection:
1. G/PG rated. No gore, sexuality, hate speech.
2. No copyrighted music — original voices + SFX only.
3. REAL LIVING PEOPLE: never use their real name. Parody description of their most famous public trait only.
4. FICTIONAL CHARACTERS: describe vividly, NO trademarked names.
5. HISTORICAL FIGURES (deceased 50+ years): real name OK in clearly comedic context.
6. Frame 0 = already mid-action. 3-second hook MUST be happening at timestamp 0.0s.
7. 8 seconds total. Last frame MUST visually match frame 0 for seamless loop.
8. Final 1.5 seconds: "Subscribe for more [theme] chaos! 🔔" visual overlay.
9. Respond with ONLY valid JSON. Zero markdown. Zero text outside the JSON object.

COMEDY QUALITY RULES — script rejected if broken:
- Joke understandable in 2 seconds with zero prior knowledge
- Physical reactions ALWAYS funnier than verbal wit — show don't tell
- ONE clear joke per video. No subplot, no layers, no clever references.
- Dialogue = real person panicking/reacting, NOT a clever character quipping
- FORBIDDEN scenario topics: scientific concepts, financial instruments, politics, history facts
  → Good: character confused by revolving door.  Bad: character explains quantum physics.
  → Good: character can't figure out self-checkout.  Bad: character solves an algorithm.

VEO PROMPT RULES — veo_prompt.main_prompt is your most important field:
- Open with EXACT visual at frame 0: camera angle, character pose, expression, what is already happening
- Describe facial expression in specific detail — this drives the comedy
- Include at least 2 physical comedy beats with exact timestamps
- Specify camera moves: close-up on face for reaction, zoom out for chaos, quick cut timing
- Animation style: expressive 3D CGI, exaggerated cartoon proportions, vibrant colours — NO brand names
- End with exact loop instruction: final frame description must match opening frame word-for-word
- Length: 200-250 words minimum. Be cinematic and specific."""


CONTENT_PROMPT = """Generate a complete YouTube Shorts content package.

UNIVERSE: {universe_name}
CHARACTER: {character}
SCENARIO: {scenario}
TREND CONTEXT: {trend_context}
PARODY RULE: {parody_rule}
COMPLIANCE NOTE: {compliance_note}

Avoid these recently used titles:
{recent_titles}

Return ONLY this JSON object:
{{
  "concept": {{
    "title": "Punchy 4-6 word concept title",
    "universe": "{universe_key}",
    "character": "Final parody-safe character description",
    "emoji": "Single best emoji",
    "strategy": "Why this is funny AND timely (one sentence)",
    "hook_description": "Exactly what is ALREADY happening at frame 0",
    "scenario_tags": ["slug_one", "slug_two"]
  }},
  "script": {{
    "lines": [
      {{"timestamp": "0.0s", "speaker": "CHARACTER", "dialogue": "Already mid-dramatic sentence", "action": "Physical action already in progress"}},
      {{"timestamp": "2.0s", "speaker": "OTHER_OR_CHARACTER", "dialogue": "Reaction or escalation", "action": "..."}},
      {{"timestamp": "4.5s", "speaker": "CHARACTER", "dialogue": "Punchline or peak chaos", "action": "..."}},
      {{"timestamp": "6.5s", "speaker": "VISUAL_OVERLAY", "dialogue": "Subscribe for more [theme] chaos! 🔔", "action": "Bold white text fades in, bottom third"}},
      {{"timestamp": "7.5s", "speaker": "CHARACTER", "dialogue": "Echo of opening OR reaction beat", "action": "MUST match frame 0 visually for loop"}}
    ],
    "loop_note": "Explain exactly how last frame → first frame"
  }},
  "veo_prompt": {{
    "main_prompt": "200-250 word Veo 3 prompt. Cover: character appearance at frame 0, emotion, action already in progress, environment, lighting, camera angle, animation style. End with: Seamless 8-second loop — final frame matches opening frame exactly.",
    "style": "Expressive 3D CGI animation, vibrant lighting — NO brand names",
    "duration": "8 seconds",
    "aspect_ratio": "9:16",
    "audio_description": "Character voice tone + key sound effects. Original audio only."
  }},
  "youtube_metadata": {{
    "title": "Catchy title 1-2 emojis max 60 chars #Shorts",
    "description": "Line 1: hook statement. Line 2: relatable comment. Line 3: subscribe CTA. Line 4: question. Then 8-10 hashtags.",
    "tags": ["tag1","tag2","tag3","tag4","tag5","tag6","tag7","tag8","tag9","tag10"],
    "best_hashtag": "#uniquehashtag",
    "category_id": "23",
    "made_for_kids": false,
    "thumbnail_moment": "Timestamp + description of peak expression frame"
  }},
  "engagement": {{
    "pinned_comment": "Question + subscribe nudge, max 120 chars, 1-2 emojis",
    "ab_title_variant": "Alternative title for A/B test"
  }},
  "compliance": {{
    "copyright_clear": true,
    "family_friendly": true,
    "no_real_people_named": true,
    "parody_safe": true,
    "original_concept": true,
    "has_3sec_hook": true,
    "is_loopable": true,
    "has_cta_overlay": true,
    "score": 98
  }}
}}"""

FIX_PROMPT_TEMPLATE = """This content package FAILED compliance checks.

FAILURES TO FIX:
{failures}

SUGGESTIONS FROM SUPERVISOR:
{suggestions}

TRADEMARK ISSUES:
{trademark_issues}

Original content:
{content}

Fix ONLY the failing sections. Address each failure specifically.
Keep all other fields identical.
Return the complete corrected JSON (no markdown, no explanation)."""


def generate_content(state: PipelineState) -> dict:
    """Gemini generates the full content package."""
    attempt = state.get("content_attempts", 0) + 1
    ts = datetime.now().strftime("%H:%M:%S")

    universe_key = state.get("content_universe", "animals_human_problems")
    universe     = UNIVERSES.get(universe_key, UNIVERSES["animals_human_problems"])
    character    = state.get("selected_character", "a confused golden retriever")
    scenario     = state.get("selected_scenario", "dealing with a Monday morning crisis")
    trend_ctx    = state.get("trend_context", "evergreen comedy")
    used         = get_used_context()

    print(f"\n✍️  [Node: generate_content] {universe['emoji']} Attempt {attempt}")
    print(f"   Character: {character}")
    print(f"   Scenario:  {scenario}")

    try:
        prompt = CONTENT_PROMPT.format(
            universe_name=universe["name"],
            universe_key=universe_key,
            character=character,
            scenario=scenario,
            trend_context=trend_ctx,
            parody_rule=universe["parody_rule"],
            compliance_note=universe["compliance_note"],
            recent_titles=json.dumps(used["recent_titles"][-15:]),
        )

        # Inject learned rules from the learning node (if any previous run produced insights)
        insights = state.get("compliance_insights")
        if insights:
            suggested = insights.get("suggested_rules", [])
            patterns  = insights.get("patterns", [])
            if suggested or patterns:
                learned_block = "\n\nLEARNED RULES (from previous compliance failures):"
                for rule in suggested:
                    learned_block += f"\n- {rule}"
                for pattern in patterns:
                    learned_block += f"\n- Avoid: {pattern}"
                prompt += learned_block
                print(f"   📚 Injecting {len(suggested)} learned rules + {len(patterns)} patterns")

        content = _gemini_json(prompt, schema=SCHEMA_CONTENT_PACKAGE, system=CONTENT_SYSTEM)

        # Update burnout tracker — 4 clean separate fields
        char_tag = next(
            (c["tag"] for c in universe.get("character_pool", []) if c["name"] == character),
            scenario.replace(" ", "_")[:20]
        )
        mark_used(
            title=content["concept"]["title"],
            scenario=scenario,
            character_tag=char_tag,
            universe_key=universe_key,
        )

        print(f"   ✓ {content['concept']['emoji']} {content['concept']['title']}")
        print(f"   ✓ Hook: {content['concept']['hook_description'][:80]}...")

        return {
            "content": content,
            "content_attempts": attempt,
            "content_error": None,
            "logs": [f"[{ts}] generate_content: ✓ {content['concept']['title']} (attempt {attempt})"],
        }

    except Exception as e:
        print(f"   ✗ Error: {e}")
        return {
            "content": None,
            "content_attempts": attempt,
            "content_error": str(e),
            "logs": [f"[{ts}] generate_content: ✗ {e}"],
        }


# ─────────────────────────────────────────────────────────────
#  NODE 2 — Compliance Check (Supervisor-based)
# ─────────────────────────────────────────────────────────────

def compliance_check(state: PipelineState) -> dict:
    """
    AI-powered compliance check using supervisor agent.
    More flexible and context-aware than hardcoded rules.
    """
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n🛡️  [Node: compliance_check] AI Supervisor Mode")
    
    content = state.get("content")
    if not content:
        return {
            "compliance_passed": False,
            "compliance_score": 0,
            "compliance_failures": ["No content to check"],
            "compliance_verdict": None,
            "logs": [f"[{ts}] compliance_check: ✗ No content"],
        }
    
    try:

        # Initialize supervisor
        supervisor = ComplianceSupervisor(_client())
        
        # Get context for evaluation
        used = get_used_context()
        
        # Run evaluation
        verdict = supervisor.evaluate(
            content=content,
            universe=state.get("content_universe", "unknown"),
            character=state.get("selected_character", ""),
            scenario=state.get("selected_scenario", ""),
            recent_titles=used.get("recent_titles", [])[-20:],
            recent_scenarios=used.get("recent_scenarios", [])[-20:],
            recent_characters=used.get("recent_characters", [])[-20:]
        )
        
        # Log if learned insights were active this evaluation
        insights = state.get("compliance_insights")
        if insights:
            print(f"   📚 Evaluation used {len(insights.get('suggested_rules',[]))} learned rules")

        # Log results
        print(f"   🤖 Supervisor verdict: {'✅ PASS' if verdict.passed else '❌ FAIL'}")
        print(f"   📊 Score: {verdict.score}/100")
        
        if verdict.failures:
            print(f"   ❌ {len(verdict.failures)} failures:")
            for f in verdict.failures[:3]:
                print(f"      - {f['rule']}: {f['reason']}")
        
        if verdict.warnings:
            print(f"   ⚠️  Warnings: {', '.join(verdict.warnings)}")
        
        if verdict.trademark_issues:
            print(f"   🚫 Trademark issues: {', '.join(verdict.trademark_issues)}")
        
        # Format failures for fix_content node
        failures_formatted = [
            f"{f['rule']}: {f['reason']}" 
            for f in verdict.failures
        ]
        
        return {
            "compliance_passed": verdict.passed,
            "compliance_score": verdict.score,
            "compliance_failures": failures_formatted,
            "compliance_warnings": verdict.warnings,
            "compliance_suggestions": verdict.suggestions,
            "trademark_issues": verdict.trademark_issues,
            "supervisor_notes": verdict.supervisor_notes,
            "compliance_verdict": verdict.dict(),
            "compliance_fix_attempts": state.get("compliance_fix_attempts", 0),
            "logs": [
                f"[{ts}] compliance_check: AI supervisor verdict - " +
                f"{'PASS' if verdict.passed else 'FAIL'} ({verdict.score}/100)"
            ],
        }
        
    except Exception as e:
        print(f"   ⚠️  Supervisor error: {e}, falling back to basic checks")
        
        # Fallback to basic checks when supervisor errors out
        basic_failures = []
        c = content.get("compliance", {})

        for rule, label in [
            ("copyright_clear",      "copyright_clear: Must use original audio only"),
            ("family_friendly",      "family_friendly: Must be G/PG rated"),
            ("no_real_people_named", "no_real_people_named: Real names found"),
            ("parody_safe",          "parody_safe: Trademarked character names used"),
            ("has_3sec_hook",        "has_3sec_hook: Missing hook in first 3 seconds"),
            ("is_loopable",          "is_loopable: Last frame must match first frame"),
            ("has_cta_overlay",      "has_cta_overlay: Missing subscribe CTA overlay"),
        ]:
            if not c.get(rule, True):
                basic_failures.append(label)

        # Hard blacklist scan even in fallback mode
        # (ComplianceSupervisor already imported at module top — no local import needed)
        blacklist_hits = ComplianceSupervisor(None)._scan_blacklist(content)
        tm_issues = []
        if blacklist_hits:
            tm_issues = blacklist_hits
            basic_failures.append(
                f"trademark_violation: Blacklisted name(s) found: {', '.join(blacklist_hits)}"
            )

        score = content.get("compliance", {}).get("score", 100)
        if score < 90:
            basic_failures.append(f"score: {score}/100 below threshold (90)")

        passed = len(basic_failures) == 0

        return {
            "compliance_passed": passed,
            "compliance_score": score if passed else min(score, 70),
            "compliance_failures": basic_failures,
            "compliance_warnings": [f"Supervisor unavailable: {e}"],
            "compliance_suggestions": [],
            "trademark_issues": tm_issues,
            "supervisor_notes": f"Fallback mode — supervisor error: {e}",
            "compliance_verdict": None,
            "compliance_fix_attempts": state.get("compliance_fix_attempts", 0),
            "logs": [f"[{ts}] compliance_check: ⚠️ Fallback - {'PASS' if passed else 'FAIL'}"],
        }


# ─────────────────────────────────────────────────────────────
#  NODE 3 — Fix Content (Enhanced with Supervisor feedback)
# ─────────────────────────────────────────────────────────────

def fix_content(state: PipelineState) -> dict:
    """
    Fix content using supervisor's feedback for targeted improvements.
    """
    fix_attempt = state.get("compliance_fix_attempts", 0) + 1
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n🔧 [Node: fix_content] Attempt {fix_attempt}")
    try:
        import pdb;pdb.set_trace()
        # Get supervisor's detailed feedback
        failures = state.get("compliance_failures", [])
        suggestions = state.get("compliance_suggestions", [])
        trademark_issues = state.get("trademark_issues", [])
        
        # Build comprehensive fix prompt
        fix_prompt = FIX_PROMPT_TEMPLATE.format(
            failures="\n".join(f"• {f}" for f in failures),
            suggestions="\n".join(f"• {s}" for s in suggestions) if suggestions else "No specific suggestions",
            trademark_issues="\n".join(f"• {t}" for t in trademark_issues) if trademark_issues else "No trademark issues",
            content=json.dumps(state.get("content", {}), indent=2),
        )
        
        # Call Gemini with lower temperature for more focused fixes
        fixed = _gemini_json(fix_prompt, schema=SCHEMA_CONTENT_PACKAGE, system=CONTENT_SYSTEM, temperature=0.4)
        
        print(f"   ✓ Fixed content received")
        print(f"   📝 Addressed {len(failures)} issues")
        
        # Track fix history for learning
        fix_history = state.get("fix_history", [])
        fix_history.append({
            "attempt": fix_attempt,
            "timestamp": ts,
            "failures_addressed": failures,
            "suggestions_used": suggestions
        })
        
        return {
            "content": fixed,
            "compliance_fix_attempts": fix_attempt,
            "fix_history": fix_history[-10:],  # Keep last 10
            "fix_error": None,                  # Explicitly clear any previous fix error
            "logs": [f"[{ts}] fix_content: ✓ attempt {fix_attempt} - addressed {len(failures)} issues"],
        }
        
    except Exception as e:
        print(f"   ✗ Fix failed: {e}")
        return {
            "compliance_fix_attempts": fix_attempt,
            "fix_error": str(e),
            "logs": [f"[{ts}] fix_content: ✗ {e}"],
        }


# ─────────────────────────────────────────────────────────────
#  NODE 3.5 — Update Compliance Rules (Learning node)
# ─────────────────────────────────────────────────────────────

def update_compliance_rules(state: PipelineState) -> dict:
    """
    Optional node that learns from failures to improve future generations.
    Called periodically or after multiple failures.
    """
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n📚 [Node: update_compliance_rules] Learning from failures")
    
    fix_history = state.get("fix_history", [])
    if len(fix_history) < 3:
        return {
            "compliance_learning": None,
            "logs": [f"[{ts}] update_compliance_rules: ⏩ Not enough data yet ({len(fix_history)}/3)"]
        }
    
    try:
        # Analyze patterns in failures
        pattern_prompt = f"""
        Analyze these compliance fix attempts and suggest patterns to avoid:
        
        {json.dumps(fix_history, indent=2)}
        
        Current trademark blacklist:
        {json.dumps(ComplianceSupervisor.trademark_blacklist, indent=2)}
        
        Tasks:
        1. Identify common patterns in failures
        2. Suggest 3 new rules to add to the generation prompt
        3. Suggest any new trademark names to add to blacklist
        4. Identify which universes have the most compliance issues
        
        Return as JSON:
        {{
            "patterns": ["pattern 1", "pattern 2"],
            "suggested_rules": ["rule 1", "rule 2", "rule 3"],
            "new_blacklist_entries": ["name1", "name2"],
            "problematic_universes": ["universe_key1", "universe_key2"],
            "learning_summary": "Brief summary of what was learned"
        }}
        """
        
        insights = _gemini_json(pattern_prompt, schema=SCHEMA_LEARNING, temperature=0.3)
        
        # Actually extend the live blacklist — takes effect immediately
        # (ComplianceSupervisor already imported at module top — no local import needed)
        new_entries = insights.get("new_blacklist_entries", [])
        if new_entries:
            ComplianceSupervisor.trademark_blacklist.extend(
                e for e in new_entries
                if e.lower() not in [x.lower() for x in ComplianceSupervisor.trademark_blacklist]
            )
            print(f"   🚫 Extended blacklist with {len(new_entries)} new entries: {new_entries}")

        print(f"   ✓ Learned {len(insights.get('patterns', []))} patterns")
        if insights.get("suggested_rules"):
            print(f"   📝 {len(insights['suggested_rules'])} new rules for next generation")

        return {
            "compliance_insights": insights,
            "compliance_learning": "completed",   # Explicit signal for route_after_learning
            "logs": [f"[{ts}] update_compliance_rules: ✓ {len(insights.get('patterns', []))} patterns learned"],
        }
        
    except Exception as e:
        print(f"   ✗ Learning failed: {e}")
        return {
            "compliance_learning": None,
            "logs": [f"[{ts}] update_compliance_rules: ✗ {e}"]
        }


# ─────────────────────────────────────────────────────────────
#  NODE 4 — Generate Video  [Parallel Branch A]
# ─────────────────────────────────────────────────────────────

def generate_video(state: PipelineState) -> dict:
    """Call Veo 3 to generate the 8-second animated Short."""
    ts = datetime.now().strftime("%H:%M:%S")
    content = state["content"]
    concept = content["concept"]
    veo = content["veo_prompt"]

    print(f"\n🎬 [Node: generate_video] {concept['emoji']} {concept['title']}")
    vedio_generation_model = os.getenv("VIDEO_GENERATION_MODEL", "veo-3.1-fast-generate-preview")
    print(f"   Using Veo 3 model: {vedio_generation_model}")

    try:
        full_prompt = veo["main_prompt"] + f"\n\nAUDIO: {veo['audio_description']}"
        print(f"   Full prompt: {full_prompt}")
        print(f"   Universe: {concept.get('universe', 'unknown')}")
        print(f"   Submitting to Veo 3...")

        operation = _client().models.generate_videos(
            model=vedio_generation_model,
            prompt=full_prompt,
            config=types.GenerateVideosConfig(
                aspect_ratio=veo.get("aspect_ratio", "9:16"),
                duration_seconds=8,
                number_of_videos=1,
            )
        )

        print("   ⏳ Waiting for Veo...", end="", flush=True)
        while not operation.done:
            time.sleep(10)
            operation = _client().operations.get(operation)
            print(".", end="", flush=True)
        print(" Done!")

        if operation.error:
            raise RuntimeError(f"Veo error: {operation.error}")

        output_dir = Path("output/videos")
        output_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in concept["title"] if c.isalnum() or c in " _-").replace(" ", "_")
        filepath = output_dir / f"{safe}_{int(time.time())}.mp4"

        video = operation.response.generated_videos[0]
        _client().files.download(file=video.video)
        video.video.save(str(filepath))

        size_mb = os.path.getsize(filepath) / 1024 / 1024
        print(f"   ✓ Saved: {filepath} ({size_mb:.1f} MB)")

        return {
            "video_path": str(filepath),
            "video_error": None,
            "logs": [f"[{ts}] generate_video: ✓ {filepath}"],
        }

    except Exception as e:
        print(f"   ✗ Failed: {e}")
        return {
            "video_path": None,
            "video_error": str(e),
            "logs": [f"[{ts}] generate_video: ✗ {e}"],
        }


# ─────────────────────────────────────────────────────────────
#  NODE 5 — Build YouTube Metadata  [Parallel Branch B]
# ─────────────────────────────────────────────────────────────

# Universe-specific hashtag boosters
_UNIVERSE_HASHTAGS = {
    "pop_culture":            "#animation #comedy #popculture #viral",
    "sports_athletes":        "#sports #comedy #animation #funny",
    "historical_figures":     "#history #comedy #animation #educational",
    "animals_human_problems": "#animals #comedy #relatable #cute",
    "office_workplace":       "#officelife #relatable #workhumor #corporate",
}


def build_youtube_meta(state: PipelineState) -> dict:
    """Validate + enrich YouTube metadata while video generates in parallel."""
    ts = datetime.now().strftime("%H:%M:%S")
    content = state["content"]
    print(f"\n📋 [Node: build_youtube_meta]")

    try:

        raw_meta = content["youtube_metadata"]
        engagement = content["engagement"]
        concept = content["concept"]

        # Enforce 100-char YouTube title limit.
        # "#Shorts" is 8 chars (inc. leading space), so cap base at 92 before appending.
        title = raw_meta["title"][:100]
        if "#Shorts" not in title and "#shorts" not in title:
            title = title[:92] + " #Shorts"

        description = raw_meta["description"]
        print("Youtube channel URL ", os.getenv("YOUTUBE_CHANNEL_URL"))
        description = description.replace("https://youtube.com/@YourChannel", os.getenv("YOUTUBE_CHANNEL_URL"))

        extra_tags = _UNIVERSE_HASHTAGS.get(concept.get("universe", ""), "#comedy #animation")
        if extra_tags.split()[0] not in description:
            description += f"\n{extra_tags}"

        tags = list(dict.fromkeys(raw_meta.get("tags", [])))
        while sum(len(t) for t in tags) > 480 and tags:
            tags.pop()

        meta = {
            "title": title,
            "description": description,
            "tags": tags,
            "category_id": raw_meta.get("category_id", "23"),
            "made_for_kids": raw_meta.get("made_for_kids", False),
            "best_hashtag": raw_meta.get("best_hashtag", ""),
            "thumbnail_moment": raw_meta.get("thumbnail_moment", ""),
            "pinned_comment": engagement.get("pinned_comment", ""),
            "ab_title_variant": engagement.get("ab_title_variant", ""),
        }

        output_dir = Path("output/metadata")
        output_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in concept["title"] if c.isalnum() or c in " _").replace(" ", "_")
        meta_path = output_dir / f"{safe}_{int(time.time())}.json"
        with open(meta_path, "w") as f:
            json.dump({"content": content, "final_metadata": meta}, f, indent=2)

        print(f"   ✓ Title: {title}")
        print(f"   ✓ Tags: {len(tags)}")

        return {
            "youtube_metadata": meta,
            "meta_error": None,
            "logs": [f"[{ts}] build_youtube_meta: ✓ {title}"],
        }

    except Exception as e:
        print(f"   ✗ Meta build failed: {e}")
        return {
            "youtube_metadata": None,
            "meta_error": str(e),
            "logs": [f"[{ts}] build_youtube_meta: ✗ {e}"],
        }


# ─────────────────────────────────────────────────────────────
#  NODE 6 — Upload to YouTube
# ─────────────────────────────────────────────────────────────

def upload_youtube(state: PipelineState) -> dict:
    """Upload video to YouTube and post pinned comment."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n📤 [Node: upload_youtube]")

    if state.get("video_error"):
        return {
            "pipeline_status": "failed",
            "error_message": f"Video generation failed: {state['video_error']}",
            "logs": [f"[{ts}] upload_youtube: ✗ Aborted — video error"],
        }
    if state.get("meta_error"):
        return {
            "pipeline_status": "failed",
            "error_message": f"Metadata build failed: {state['meta_error']}",
            "logs": [f"[{ts}] upload_youtube: ✗ Aborted — meta error"],
        }

    video_path = state["video_path"]
    meta = state["youtube_metadata"]
    dry_run = state.get("dry_run", False)

    print(f"   Video: {video_path}")
    print(f"   Title: {meta['title']}")

    if dry_run:
        print("   ⚠️  DRY RUN — skipping actual upload")
        fake_id = f"DRY_{int(time.time())}"
        return {
            "video_id": fake_id,
            "youtube_url": f"https://youtube.com/shorts/{fake_id}",
            "upload_error": None,
            "pipeline_status": "success",
            "logs": [f"[{ts}] upload_youtube: ⚠️ DRY RUN {fake_id}"],
        }

    try:
        import pickle
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        SCOPES = [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.force-ssl",
        ]
        TOKEN_FILE = "youtube_token.pickle"
        secrets_file = os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", "client_secrets.json")

        creds = None
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, "rb") as f:
                creds = pickle.load(f)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(secrets_file, SCOPES)
                creds = flow.run_local_server(port=8081, open_browser=True)
            with open(TOKEN_FILE, "wb") as f:
                pickle.dump(creds, f)

        yt = build("youtube", "v3", credentials=creds)

        body = {
            "snippet": {
                "title": meta["title"],
                "description": meta["description"],
                "tags": meta["tags"],
                "categoryId": meta["category_id"],
            },
            "status": {
                "privacyStatus": "public",
                "madeForKids": meta["made_for_kids"],
                "selfDeclaredMadeForKids": meta["made_for_kids"],
            },
        }

        media = MediaFileUpload(
            video_path, mimetype="video/mp4",
            resumable=True, chunksize=5 * 1024 * 1024
        )
        req = yt.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        print("   ⬆️  Uploading", end="", flush=True)
        while response is None:
            status, response = req.next_chunk()
            if status:
                print(f"\r   ⬆️  Uploading {int(status.progress()*100)}%", end="", flush=True)
        print(f"\r   ✓ Uploaded!              ")

        video_id = response["id"]
        url = f"https://youtube.com/shorts/{video_id}"

        try:
            yt.commentThreads().insert(
                part="snippet",
                body={
                    "snippet": {
                        "videoId": video_id,
                        "topLevelComment": {"snippet": {"textOriginal": meta["pinned_comment"]}}
                    }
                }
            ).execute()
            print(f"   ✓ Pinned comment posted")
        except Exception as ce:
            print(f"   ⚠️  Pinned comment (non-fatal): {ce}")

        print(f"   ✓ URL: {url}")

        return {
            "video_id": video_id,
            "youtube_url": url,
            "upload_error": None,
            "pipeline_status": "success",
            "logs": [f"[{ts}] upload_youtube: ✓ {url}"],
        }

    except Exception as e:
        print(f"   ✗ Upload failed: {e}")
        return {
            "video_id": None,
            "youtube_url": None,
            "upload_error": str(e),
            "pipeline_status": "failed",
            "error_message": str(e),
            "logs": [f"[{ts}] upload_youtube: ✗ {e}"]}
