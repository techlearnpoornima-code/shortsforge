import json
import re

def _parse_json(text: str) -> dict:
    """Strip markdown fences and attempt safe JSON parsing with repair."""

    text = text.strip()

    # Remove markdown fences
    text = re.sub(r"^```json\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^```\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)

    text = text.strip()

    try:
        return json.loads(text)

    except json.JSONDecodeError as e:
        print("⚠️ JSON parsing failed:", e)
        print("Attempting auto-repair...")

        # Try to auto-close JSON
        repaired = _attempt_json_repair(text)

        try:
            return json.loads(repaired)
        except Exception:
            print("❌ Repair failed.")
            print("Last 500 chars:\n", text[-500:])
            raise


def _attempt_json_repair(text: str) -> str:
    """Naive repair for truncated JSON."""

    # Close open quotes
    if text.count('"') % 2 != 0:
        text += '"'

    # Close braces
    open_braces = text.count("{")
    close_braces = text.count("}")
    text += "}" * (open_braces - close_braces)

    # Close brackets
    open_brackets = text.count("[")
    close_brackets = text.count("]")
    text += "]" * (open_brackets - close_brackets)

    return text


def _parse_response(raw: str) -> dict:
    """
    Safely parse supervisor JSON response.
    Strips markdown fences and repairs minor truncation.
    """

    raw = raw.strip()

    # Remove accidental markdown fences
    raw = re.sub(r"^```json\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"^```\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)

    try:
        return json.loads(raw)

    except json.JSONDecodeError as e:
        print("⚠️ Supervisor JSON parse failed:", e)
        print("Last 500 chars:\n", raw[-500:])
        raise