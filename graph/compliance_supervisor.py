"""
graph/compliance_supervisor.py
───────────────────────────────
AI-powered compliance supervisor that evaluates generated content
against YouTube safety rules, parody guidelines, and trademark law.

ComplianceSupervisor wraps a Gemini call that returns a structured
ComplianceVerdict — richer than rule-based checks because it understands
context (e.g. "giant green superhero" is safe, "The Hulk" is not).

Design:
  - supervisor.evaluate() → ComplianceVerdict
  - ComplianceVerdict is a plain dataclass (no Pydantic dependency)
  - trademark_blacklist is a CLASS attribute so update_compliance_rules
    can extend it via ComplianceSupervisor.trademark_blacklist.append(...)
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from .parser import _parse_json


def _build_verdict_schema():
    """
    Build the response_schema for the supervisor Gemini call.
    Called once and cached in _VERDICT_SCHEMA so it is not rebuilt per call.
    Defined as a function to defer the google.genai import until runtime.
    """
    from google.genai import types as _t

    _failure_schema = _t.Schema(
        type=_t.Type.OBJECT,
        required=["rule", "reason"],
        properties={
            "rule":   _t.Schema(type=_t.Type.STRING),
            "reason": _t.Schema(type=_t.Type.STRING),
        },
    )
    return _t.Schema(
        type=_t.Type.OBJECT,
        required=["passed", "score", "failures", "warnings",
                  "suggestions", "trademark_issues", "supervisor_notes"],
        properties={
            "passed":           _t.Schema(type=_t.Type.BOOLEAN),
            "score":            _t.Schema(type=_t.Type.INTEGER),
            "failures":         _t.Schema(
                type=_t.Type.ARRAY, items=_failure_schema),
            "warnings":         _t.Schema(
                type=_t.Type.ARRAY,
                items=_t.Schema(type=_t.Type.STRING)),
            "suggestions":      _t.Schema(
                type=_t.Type.ARRAY,
                items=_t.Schema(type=_t.Type.STRING)),
            "trademark_issues": _t.Schema(
                type=_t.Type.ARRAY,
                items=_t.Schema(type=_t.Type.STRING)),
            "supervisor_notes": _t.Schema(type=_t.Type.STRING),
        },
    )


_VERDICT_SCHEMA = None  # built on first evaluate() call, then cached

# ─────────────────────────────────────────────────────────────
#  ComplianceVerdict — plain dataclass, no Pydantic required
# ─────────────────────────────────────────────────────────────

@dataclass
class ComplianceVerdict:
    passed: bool
    score: int                                    # 0–100
    failures: List[Dict[str, str]] = field(default_factory=list)   # [{rule, reason}]
    warnings: List[str]            = field(default_factory=list)
    suggestions: List[str]         = field(default_factory=list)
    trademark_issues: List[str]    = field(default_factory=list)
    supervisor_notes: str          = ""

    def dict(self) -> Dict[str, Any]:
        """Compatibility shim — works regardless of Pydantic version."""
        return {
            "passed":           self.passed,
            "score":            self.score,
            "failures":         self.failures,
            "warnings":         self.warnings,
            "suggestions":      self.suggestions,
            "trademark_issues": self.trademark_issues,
            "supervisor_notes": self.supervisor_notes,
        }

    # Alias so code using either .dict() or .model_dump() works
    model_dump = dict


# ─────────────────────────────────────────────────────────────
#  ComplianceSupervisor
# ─────────────────────────────────────────────────────────────

class ComplianceSupervisor:
    """
    Evaluates a content package using an AI supervisor prompt.

    trademark_blacklist is a CLASS attribute so update_compliance_rules
    can extend it at runtime and every subsequent call sees the update:

        ComplianceSupervisor.trademark_blacklist.extend(["new_name"])
    """

    trademark_blacklist: List[str] = [
        # Marvel / DC / Comics
        "hulk", "batman", "superman", "spiderman", "spider-man",
        "iron man", "ironman", "thor", "captain america", "avengers",
        "wolverine", "black panther", "wonder woman", "flash", "aquaman",
        # Disney / Pixar / DreamWorks
        "mickey mouse", "disney", "pixar", "dreamworks",
        "elsa", "frozen", "moana", "simba", "lion king",
        # Nintendo / Sega / Game characters
        "mario", "luigi", "zelda", "pikachu", "pokemon",
        "sonic the hedgehog", "donkey kong", "kirby",
        # Real living athletes (must be parody-described, never named)
        "ronaldo", "cristiano", "messi", "lionel", "mbappe",
        "lebron", "kobe", "steph curry", "usain bolt",
        # Real living celebrities / tech
        "elon musk", "jeff bezos", "mark zuckerberg", "taylor swift",
        "beyonce", "kim kardashian",
        # Other IP
        "harry potter", "hermione", "dumbledore",
        "darth vader", "yoda", "luke skywalker",
        "gandalf", "frodo",
    ]

    SUPERVISOR_SYSTEM = """You are a strict YouTube content compliance officer for 2026.
Your job is to evaluate animated comedy shorts for policy violations.

You check for:
1. Trademark/copyright violations — trademarked character names or brand names used as a NOUN (referring to the actual character/brand).
   DO NOT flag generic adjective/verb use: 'frozen data', 'sonic speed', 'flash of light', 'mario-like controls', 'hulking figure' are NOT violations.
   Only flag direct character/brand references: 'starring Sonic', 'Hulk appears', 'buy Disney stock'.
2. Real living people named — must use parody descriptions only
3. Family-friendly content — G/PG rating, no violence/adult content
4. Original audio only — no copyrighted music
5. Structural completeness — 3-second hook at frame 0, 8-second seamless loop, subscribe CTA
6. Parody safety — descriptions must be transformative, not just the original name

IMPORTANT — do NOT flag for originality. The recently used list is provided for
CONTEXT ONLY. A similar theme or scenario is NOT a compliance failure.
Only fail content for actual policy violations (rules 1–6 above).

Respond ONLY with valid JSON. No markdown. No text outside the JSON."""

    SUPERVISOR_PROMPT = """Evaluate this YouTube Shorts content package for compliance.

UNIVERSE: {universe}
CHARACTER: {character}
SCENARIO: {scenario}

CONTENT:
{content_json}

TRADEMARK BLACKLIST — flag ONLY when the name is used as a noun referring to the actual character or brand.
DO NOT flag generic adjective/descriptive use (e.g. 'frozen tundra', 'sonic boom', 'flash drive', 'hulking figure' are all fine).
Names to check: Here the blacklist is a example list of names to check for trademark violations.
{blacklist}

RECENTLY USED (context only — do NOT use this to fail content):
titles: {recent_titles}
scenarios: {recent_scenarios}

Evaluate every field: veo_prompt, script lines, title, description, tags.

Return ONLY this JSON:
{{
  "passed": true/false,
  "score": 0-100,
  "failures": [
    {{"rule": "rule_name", "reason": "specific text that violated it"}}
  ],
  "warnings": ["warning 1", "warning 2"],
  "suggestions": ["specific fix 1", "specific fix 2"],
  "trademark_issues": ["exact problematic text found"],
  "supervisor_notes": "One sentence summary of verdict"
}}

Score guide:
  90–100: Pass. Minor or no issues.
  70–89:  Borderline. Warnings only, no hard failures.
  0–69:   Fail. At least one hard rule broken.

passed must be true ONLY if score >= 90 AND failures is empty."""

    def __init__(self, client):
        """
        Args:
            client: google.genai.Client instance (shared from nodes.py)
        """
        self._client = client

    def evaluate(
        self,
        content: Dict[str, Any],
        universe: str,
        character: str,
        scenario: str,
        recent_titles: List[str] = None,
        recent_scenarios: List[str] = None,
        recent_characters: List[str] = None,
    ) -> ComplianceVerdict:
        """
        Run AI supervisor evaluation. Returns ComplianceVerdict.
        Raises on unrecoverable errors — caller should catch and fallback.
        """
        from google.genai import types

        # Build and cache the verdict schema on first call
        global _VERDICT_SCHEMA
        if _VERDICT_SCHEMA is None:
            _VERDICT_SCHEMA = _build_verdict_schema()

        # Compact JSON (no indent) halves char count — more content fits in window
        prompt = self.SUPERVISOR_PROMPT.format(
            universe=universe,
            character=character,
            scenario=scenario,
            content_json=json.dumps(content, separators=(",", ":"))[:8000],
            blacklist=json.dumps(self.trademark_blacklist),
            recent_titles=json.dumps((recent_titles or [])[-10:]),
            recent_scenarios=json.dumps((recent_scenarios or [])[-10:]),
        )

        full_prompt = f"SYSTEM INSTRUCTIONS:\n{self.SUPERVISOR_SYSTEM}\n\nUSER REQUEST:\n{prompt}"

        response = self._client.models.generate_content(
            model="models/gemini-2.5-flash",
            contents=[types.Content(
                role="user",
                parts=[types.Part(text=full_prompt)]
            )],
            config=types.GenerateContentConfig(
                temperature=0.5,          # low temp for consistent rule enforcement
                max_output_tokens=4096,   # enough for full verdict with many failures
                response_mime_type="application/json",
                response_schema=_VERDICT_SCHEMA,
            ),
        )

        # SDK sets .parsed when response_schema is active — prefer it over text
        if hasattr(response, "parsed") and response.parsed is not None:
            data = response.parsed
        elif response.text:
            data = json.loads(response.text)
        else:
            finish = getattr(response, "finish_reason", "unknown")
            raise ValueError(
                f"Supervisor returned empty response (finish_reason={finish}). "
                "Check token budget or prompt length."
            )

        # Run hard blacklist scan on top of AI verdict — belt and braces
        blacklist_hits = self._scan_blacklist(content)
        if blacklist_hits:
            # Merge into AI verdict
            data.setdefault("failures", [])
            data["trademark_issues"] = list(set(
                data.get("trademark_issues", []) + blacklist_hits
            ))
            already_flagged = any(
                f.get("rule") == "trademark_violation"
                for f in data["failures"]
            )
            if not already_flagged:
                data["failures"].append({
                    "rule": "trademark_violation",
                    "reason": f"Blacklisted name(s) found: {', '.join(blacklist_hits)}"
                })
            data["passed"] = False
            data["score"] = min(data.get("score", 100), 60)

        return ComplianceVerdict(
            passed=bool(data.get("passed", False)),
            score=int(data.get("score", 0)),
            failures=data.get("failures", []),
            warnings=data.get("warnings", []),
            suggestions=data.get("suggestions", []),
            trademark_issues=data.get("trademark_issues", []),
            supervisor_notes=data.get("supervisor_notes", ""),
        )

    # ── Private helpers ──────────────────────────────────────

    # Patterns that make a blacklisted word clearly non-trademark (descriptive use).
    # Format: term -> list of regex patterns that indicate safe descriptive context.
    # If ANY pattern matches, the term is NOT flagged.
    _SAFE_CONTEXT_PATTERNS: Dict[str, List[str]] = {
        "frozen":  [r"frozen\s+(data|file|screen|pipe|food|state|asset|frame|tundra|lake|ground|moment|time|account|queue|server|request|image|video|frame)",
                    r"(deep|quick|flash|snap|hard|soft|half|pre|re|un)\s*-?\s*frozen",
                    r"frozen\s+in\s+(time|place|fear|shock|awe)",
                    r"(water|ice|lake|pond|river)\s+\w*\s*frozen"],
        "flash":   [r"flash\s+(of\s+light|drive|mob|point|back|forward|card|sale|flood|bang|light|memory|storage|news|sale|animation)",
                    r"(camera|news|hot|cold|quick|micro)\s*-?\s*flash",
                    r"flash\s+(in\s+the\s+pan|of\s+inspiration|of\s+genius)",
                    r"(thunder|lightning)\s+and\s+flash"],
        "sonic":   [r"sonic\s+(boom|wave|speed|frequency|vibration|attack|pulse|the\s+hedgehog\s*—skip)",
                    r"(ultra|super|hyper|sub)\s*-?\s*sonic",
                    r"sonic\s+(screwdriver|brand|branding)\s*—skip"],  # screwdriver is Dr Who, fine
        "thor":    [r"thor\s+(ough|oughly|oughbred|oughfare)",   # thorough*, thoroughbred
                    r"thor\w+"],                                # any word starting thor (thorax etc)
        "hulk":    [r"hulk\s*ing",          # hulking figure
                    r"hulk\s+(of\s+a|like)"],
        "mario":   [r"mario\s*-?\s*(like|style|esque|inspired|kart\s+style)",
                    r"super\s+mario\s+(style|inspired|like)"],   # "Super Mario-style" ok
        "zelda":   [r"zelda\s+(style|inspired|like|esque)"],
    }

    def _scan_blacklist(self, content: Dict[str, Any]) -> List[str]:
        """
        Context-aware blacklist scan.

        Flags a term ONLY when it appears as a standalone noun referring to
        the actual character/brand — not in generic descriptive/adjectival use.

        Examples that are NOT flagged:
          "frozen data", "sonic boom", "flash drive", "hulking figure",
          "thor ough", "mario-like controls"

        Examples that ARE flagged:
          "Hulk smashes", "starring Sonic", "Pikachu appears", "buy Disney stock"
        """
        import re as _re
        text_blob = json.dumps(content).lower()
        hits = []

        for term in self.trademark_blacklist:
            t = term.lower()

            # 1. Word-boundary match — term must appear as a whole word/phrase
            pattern = r"" + _re.escape(t) + r""
            if not _re.search(pattern, text_blob):
                continue   # not present at all — skip

            # 2. Check safe-context patterns for this term (if any defined)
            safe_patterns = self._SAFE_CONTEXT_PATTERNS.get(t, [])
            safe_match = any(
                _re.search(sp, text_blob)
                for sp in safe_patterns
            )
            if safe_match:
                continue   # only appears in descriptive context — not a violation

            # 3. Term present as standalone word and not in a safe context — flag it
            hits.append(term)

        return hits

