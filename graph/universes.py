"""
graph/universes.py
──────────────────
Content universe definitions + burnout tracker.

Burnout tracker uses 4 clean, separate lists:
    used_titles      — full video titles        (last 100)
    used_scenarios   — scenario strings         (last 30, cooldown window)
    used_characters  — character tags           (last 30, cooldown window)
    used_universes   — universe keys            (last 10, for 3-in-a-row block)

Parody rules (per user choice):
  - Clearly fictional characters (superheroes, cartoon icons, game characters)
    → referenced by vivid description only, no trademarked names
  - Real living people (athletes, celebrities)
    → replaced with parody description of their most famous trait, never named
  - Historical figures (deceased 50+ years)
    → can be used by real name in clearly comedic context
"""

import json
import random
from pathlib import Path

# ─────────────────────────────────────────────────────────────
#  BURNOUT TRACKER — 4 clean, separate tracking lists
# ─────────────────────────────────────────────────────────────

BURNOUT_FILE       = Path("output/burnout_tracker.json")
SCENARIO_COOLDOWN  = 30   # don't reuse a scenario string for N videos
CHARACTER_COOLDOWN = 30   # don't reuse a character tag for N videos
UNIVERSE_HISTORY   = 10   # how many recent universe picks to remember


def _empty_tracker() -> dict:
    return {
        "used_titles":     [],
        "used_scenarios":  [],   # scenario strings only
        "used_characters": [],   # character tags only
        "used_universes":  [],   # universe keys only
        "total_generated": 0,
    }


def load_burnout() -> dict:
    if BURNOUT_FILE.exists():
        data = json.loads(BURNOUT_FILE.read_text())
        # Migrate legacy trackers missing the new fields
        for key in ("used_characters", "used_universes"):
            if key not in data:
                data[key] = []
        return data
    return _empty_tracker()


def save_burnout(tracker: dict):
    BURNOUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    BURNOUT_FILE.write_text(json.dumps(tracker, indent=2))


def mark_used(title: str, scenario: str, character_tag: str, universe_key: str):
    """
    Record one completed video. Each semantic category tracked separately.

    Args:
        title:         Full video concept title
        scenario:      Scenario string (e.g. "trying yoga and failing spectacularly")
        character_tag: Short tag from character pool (e.g. "hulk_parody")
        universe_key:  Universe key (e.g. "pop_culture")
    """
    tracker = load_burnout()

    tracker["used_titles"].append(title)
    tracker["used_titles"] = tracker["used_titles"][-100:]

    tracker["used_scenarios"].append(scenario)
    tracker["used_scenarios"] = tracker["used_scenarios"][-SCENARIO_COOLDOWN * 3:]

    tracker["used_characters"].append(character_tag)
    tracker["used_characters"] = tracker["used_characters"][-CHARACTER_COOLDOWN * 3:]

    tracker["used_universes"].append(universe_key)
    tracker["used_universes"] = tracker["used_universes"][-UNIVERSE_HISTORY:]

    tracker["total_generated"] = tracker.get("total_generated", 0) + 1

    save_burnout(tracker)


def get_used_context() -> dict:
    """Return a snapshot of recent history for Gemini prompting."""
    tracker = load_burnout()
    return {
        "recent_scenarios":  tracker["used_scenarios"][-SCENARIO_COOLDOWN:],
        "recent_characters": tracker["used_characters"][-CHARACTER_COOLDOWN:],
        "recent_universes":  tracker["used_universes"][-UNIVERSE_HISTORY:],
        "recent_titles":     tracker["used_titles"][-20:],
        "total_generated":   tracker.get("total_generated", 0),
    }


# ─────────────────────────────────────────────────────────────
#  UNIVERSE DEFINITIONS
# ─────────────────────────────────────────────────────────────

UNIVERSES = {

    "pop_culture": {
        "name": "Pop Culture & Fictional Characters",
        "emoji": "🎬",
        "description": "Iconic fictional characters from movies, comics, games, cartoons in absurd everyday situations",
        "weight": 20,
        "scenario_pool": [
            "trying to do a mundane task but their powers keep getting in the way",
            "attending therapy for their signature problem",
            "on a first date gone completely wrong",
            "trying to order food at a drive-through",
            "stuck in traffic and completely losing it",
            "attempting to sleep but something keeps waking them up",
            "trying yoga / meditation and failing spectacularly",
            "calling customer service and getting put on hold",
            "trying to take a selfie but chaos ensues",
            "attempting a normal job interview",
            "dealing with a broken wifi connection",
            "trying to parallel park",
            "going through airport security",
            "attempting a cooking tutorial",
            "trying to assemble IKEA furniture",
        ],
        "character_pool": [
            {"name": "a giant rage-fuelled green superhero",                    "tag": "hulk_parody",    "parody": False},
            {"name": "a caped dark vigilante detective",                         "tag": "batman_parody",  "parody": False},
            {"name": "a web-slinging teenager superhero",                        "tag": "spidey_parody",  "parody": False},
            {"name": "a sorcerer with a glowing eye pendant",                    "tag": "strange_parody", "parody": False},
            {"name": "a galaxy-defending space knight with a laser sword",       "tag": "jedi_parody",    "parody": False},
            {"name": "a time-traveling scientist in a DeLorean",                 "tag": "doc_parody",     "parody": False},
            {"name": "a hobbit who just wants to stay home",                     "tag": "hobbit_parody",  "parody": False},
            {"name": "a yellow cartoon dad who loves donuts",                    "tag": "homer_parody",   "parody": False},
            {"name": "a blue video-game hedgehog who is always in a rush",       "tag": "sonic_parody",   "parody": False},
            {"name": "a red plumber who jumps on everything",                    "tag": "mario_parody",   "parody": False},
            {"name": "a fire-breathing dragon who is actually scared of mice",   "tag": "dragon_comedy",  "parody": False},
            {"name": "a vampire who is obsessed with dental hygiene",            "tag": "vampire_comedy", "parody": False},
        ],
        "parody_rule": "Use descriptive parody names only. Never use trademarked character names. Describe the iconic trait instead.",
        "compliance_note": "No copyrighted character names. Descriptions only. No Marvel/DC/Disney logos or branding.",
    },

    "sports_athletes": {
        "name": "Sports & Athletes",
        "emoji": "⚽",
        "description": "Sports stars (parody versions) or sporting animals in hilariously wrong situations",
        "weight": 25,
        "scenario_pool": [
            # Cross-sport fish-out-of-water (visually obvious, no explanation needed)
            "attempting a classical dance form like Kathak or Ballet for the first time and failing gracefully",
            "trying to meditate but treating every moment of silence as a competition",
            "at a cooking class treating chopping vegetables like a world record attempt",
            "going grocery shopping and unable to stop dribbling/kicking/throwing every item",
            "at the dentist treating the check-up like a high-stakes championship final",
            "trying to parallel park but approaching it like a sporting sprint start",
            "on a first date at a restaurant, celebrating ordering food like a tournament win",
            "learning to knit and treating every dropped stitch as a catastrophic defeat",
            "stuck in a traffic jam doing warm-up stretches and shadow drills in the car",
            "attempting retirement and unable to stop training at 5am even on holidays",
            "at a yoga class silently competing with everyone around them",
            "trying to take a calm passport photo but physically unable to suppress the victory pose",
            "at a kids birthday party treating pin-the-tail-on-the-donkey as the Olympics",
            "trying to learn a TikTok dance but defaulting to their sport moves every 2 seconds",
        ],
        "character_pool": [
            # Football / Soccer — global #1 sport
            {"name": "a Portuguese footballer who practises his celebration smile in every mirror he passes",          "tag": "ronaldo_parody",    "parody": True},
            {"name": "an Argentine football genius who is impossibly humble and confused by attention",                "tag": "messi_parody",      "parody": True},
            {"name": "a French teenage football superstar who texts his mum mid-match",                                "tag": "mbappe_parody",     "parody": True},
            # Cricket — massive in India, UK, Australia, South Asia
            {"name": "an Indian cricket batting legend who bows respectfully to absolutely everyone and everything",   "tag": "kohli_parody",      "parody": True},
            {"name": "a retired Indian cricket god who just wants to have chai in peace but fans won't let him",       "tag": "sachin_parody",     "parody": True},
            {"name": "an Australian cricket fast bowler who sledges the vending machine when it takes too long",       "tag": "aus_cricket_parody","parody": True},
            # Athletics
            {"name": "the world's fastest human who speaks in slow motion and takes forever to decide what to eat",   "tag": "bolt_parody",       "parody": True},
            # Tennis
            {"name": "a Swiss tennis legend who stays robotically calm while everything around him explodes",         "tag": "federer_parody",    "parody": True},
            {"name": "a Spanish tennis bull who grunts dramatically even when opening a packet of crisps",            "tag": "nadal_parody",      "parody": True},
            # Misc sports comedy — sport-agnostic
            {"name": "a sumo wrestler who is genuinely terrified of butterflies",                                     "tag": "sumo_comedy",       "parody": False},
            {"name": "a marathon runner who has a complete meltdown when forced to stand completely still",            "tag": "runner_comedy",     "parody": False},
            {"name": "a golfer who erupts in silent, face-reddening fury over the tiniest imperfection",              "tag": "golf_rage",         "parody": False},
            {"name": "a gymnast who accidentally somersaults into every room",                                         "tag": "gymnast_comedy",    "parody": False},
        ],
        "parody_rule": "Real athletes MUST use parody descriptions — describe their most famous public trait/meme, never use their real name.",
        "compliance_note": "No real athlete names. Parody their publicly known personality only.",
    },

    "historical_figures": {
        "name": "Historical Figures in Modern Life",
        "emoji": "🏛️",
        "description": "Famous historical figures (deceased 50+ years) reacting to modern technology and culture",
        "weight": 10,
        "scenario_pool": [
            # Simple visual reactions — no niche knowledge required to find funny
            "discovering the smartphone and trying to figure out what to do with it",
            "trying to order at a fast food drive-through and being overwhelmed by the menu",
            "getting stuck in a revolving door and refusing to admit defeat",
            "trying to use a self-checkout machine that keeps asking for attendant help",
            "reacting to their photo going viral on social media (millions of followers overnight)",
            "trying to understand why everyone is staring at a tiny screen instead of talking",
            "attempting to pay with a credit card for the first time and being horrified",
            "discovering air conditioning and refusing to ever leave the room",
            "trying to eat a burger without cutlery — deeply offended by the concept",
            "reacting to an electric scooter and immediately trying to ride it",
            "discovering emojis and insisting on using them to write an important letter",
            "watching a cat video on a phone and being genuinely moved to tears",
            "trying to take a selfie — very confused by which way the camera points",
            "getting a spam call and taking it completely seriously",
        ],
        "character_pool": [
            {"name": "Napoleon Bonaparte",    "tag": "napoleon",    "parody": False},
            {"name": "Cleopatra",             "tag": "cleopatra",   "parody": False},
            {"name": "Julius Caesar",         "tag": "caesar",      "parody": False},
            {"name": "Leonardo da Vinci",     "tag": "davinci",     "parody": False},
            {"name": "Isaac Newton",          "tag": "newton",      "parody": False},
            {"name": "Sherlock Holmes",       "tag": "sherlock",    "parody": False},
            {"name": "Genghis Khan",          "tag": "genghis",     "parody": False},
            {"name": "Marie Curie",           "tag": "curie",       "parody": False},
            {"name": "William Shakespeare",   "tag": "shakespeare", "parody": False},
            {"name": "Albert Einstein",       "tag": "einstein",    "parody": False},
            {"name": "Sun Tzu",               "tag": "suntzu",      "parody": False},
            {"name": "Nikola Tesla",          "tag": "tesla",       "parody": False},
        ],
        "parody_rule": "Historical figures deceased 50+ years may be used by real name in clearly comedic context.",
        "compliance_note": "Keep content clearly comedic and respectful. No defamatory or offensive portrayals.",
    },

    "animals_human_problems": {
        "name": "Animals with Human Problems",
        "emoji": "🐾",
        "description": "Animals dealing with distinctly human struggles — relatable, universal, always funny",
        "weight": 30,
        "scenario_pool": [
            "having a Monday morning crisis",
            "procrastinating on a deadline",
            "dealing with a passive-aggressive coworker",
            "going on a diet that lasts 10 minutes",
            "trying to adult for the first time",
            "dealing with impostor syndrome",
            "online dating and giving up immediately",
            "trying to wake up early and failing",
            "stress-eating after a bad day",
            "rage-quitting a video game",
            "trying to cancel a subscription",
            "sending an email to the wrong person",
            "waiting for a package that never arrives",
            "arguing with GPS directions",
        ],
        "character_pool": [
            {"name": "a golden retriever",                                  "tag": "retriever",     "parody": False},
            {"name": "a grumpy cat",                                        "tag": "grumpy_cat",    "parody": False},
            {"name": "a dramatic llama",                                    "tag": "llama",         "parody": False},
            {"name": "a tiny chihuahua with very big opinions",             "tag": "chihuahua",     "parody": False},
            {"name": "a penguin in a business suit",                        "tag": "penguin_suit",  "parody": False},
            {"name": "an over-confident peacock",                           "tag": "peacock",       "parody": False},
            {"name": "a sloth trying to meet a deadline",                   "tag": "sloth",         "parody": False},
            {"name": "an anxious hamster",                                  "tag": "hamster",       "parody": False},
            {"name": "a very tired panda",                                  "tag": "panda",         "parody": False},
            {"name": "a raccoon who steals office snacks",                  "tag": "raccoon_office","parody": False},
            {"name": "an overconfident pigeon",                             "tag": "pigeon",        "parody": False},
            {"name": "a bear trying to hibernate but neighbours are loud",  "tag": "bear_sleep",    "parody": False},
        ],
        "parody_rule": "Animals only — no parody rules needed. Full creative freedom.",
        "compliance_note": "Fully original content. No IP issues.",
    },

    "office_workplace": {
        "name": "Office & Workplace Humor",
        "emoji": "💼",
        "description": "Relatable corporate / workplace comedy — the most universally shareable content category",
        "weight": 15,
        "scenario_pool": [
            "a Monday morning Zoom call where everything goes wrong",
            "the office microwave that judges your food choices",
            "the printer that only jams during emergencies",
            "the coworker who replies-all to everything",
            "the meeting that could have been an email",
            "the passive-aggressive sticky note war",
            "the boss who uses buzzwords no one understands",
            "the intern who accidentally emails the CEO",
            "the office plant that witnesses everything and has opinions",
            "the coffee machine that starts a union",
            "performance review season causing existential dread",
            "the open-plan office where everyone hears everything",
        ],
        "character_pool": [
            {"name": "an office printer with abandonment issues",         "tag": "printer",       "parody": False},
            {"name": "a coffee machine having an existential crisis",     "tag": "coffee_machine","parody": False},
            {"name": "a laptop fan that screams during presentations",    "tag": "laptop",        "parody": False},
            {"name": "an office plant that has seen too much",            "tag": "office_plant",  "parody": False},
            {"name": "a stapler with trust issues",                       "tag": "stapler",       "parody": False},
            {"name": "a whiteboard that cannot be erased properly",       "tag": "whiteboard",    "parody": False},
            {"name": "a Zoom loading spinner that moves with intention",  "tag": "zoom_spinner",  "parody": False},
            {"name": "an overworked spreadsheet",                         "tag": "spreadsheet",   "parody": False},
        ],
        "parody_rule": "All fictional workplace characters — no parody rules needed.",
        "compliance_note": "No real companies or brands mocked by name.",
    },
}


# ─────────────────────────────────────────────────────────────
#  UNIVERSE SELECTOR
# ─────────────────────────────────────────────────────────────

def select_universe(force: str = "") -> dict:
    """
    Pick a universe using weighted random selection.

    Two hard guardrails:
      1. If the same universe appears 3 times in a row → weight set to 0 (blocked)
      2. Universe used in last 2 videos → weight reduced by 15 (soft penalty)
    """
    if force and force in UNIVERSES:
        return {"key": force, **UNIVERSES[force]}

    tracker = load_burnout()
    recent_universes = tracker.get("used_universes", [])

    keys    = list(UNIVERSES.keys())
    weights = [UNIVERSES[k]["weight"] for k in keys]

    for i, key in enumerate(keys):
        last_three = recent_universes[-3:]
        last_two   = recent_universes[-2:]

        # Hard block: same universe 3 times in a row
        if last_three == [key, key, key]:
            weights[i] = 0
            continue

        # Soft penalty: appeared in last 2 picks
        if key in last_two:
            weights[i] = max(1, weights[i] - 15)

    # Safety: if all weights somehow hit 0 (edge case), reset to base weights
    if sum(weights) == 0:
        weights = [UNIVERSES[k]["weight"] for k in keys]

    chosen_key = random.choices(keys, weights=weights, k=1)[0]
    return {"key": chosen_key, **UNIVERSES[chosen_key]}


def get_available_scenarios(universe_key: str) -> list[str]:
    """
    Return scenarios not used in the last SCENARIO_COOLDOWN videos.
    Falls back to full pool if everything is on cooldown (prevents deadlock).
    """
    tracker  = load_burnout()
    on_cooldown = set(tracker["used_scenarios"][-SCENARIO_COOLDOWN:])
    pool     = UNIVERSES[universe_key]["scenario_pool"]
    available = [s for s in pool if s not in on_cooldown]
    return available if available else pool


def get_available_characters(universe_key: str) -> list[dict]:
    """
    Return characters whose tag is not in the last CHARACTER_COOLDOWN picks.
    Falls back to full pool if everything is on cooldown.
    """
    tracker     = load_burnout()
    on_cooldown = set(tracker["used_characters"][-CHARACTER_COOLDOWN:])
    pool        = UNIVERSES[universe_key]["character_pool"]
    available   = [c for c in pool if c["tag"] not in on_cooldown]
    return available if available else pool
