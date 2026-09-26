"""Keep model control syntax out of user-facing responses."""
import json
import re


def special_action(raw: str) -> dict | None:
    cleaned = raw.strip()
    if "tool_call" not in cleaned.replace(r"\_", "_"):
        return None
    # Local models sometimes emit their training template instead of JSON.
    match = re.fullmatch(
        r"<\|tool(?:\\)?_call>\s*call:([a-zA-Z][a-zA-Z0-9_\\]*)\s*(\{.*\})\s*\\?<tool(?:\\)?_call\|>",
        cleaned, re.DOTALL,
    )
    if match:
        try:
            arguments = json.loads(match[2])
            if isinstance(arguments, dict):
                name = match[1].replace(r"\_", "_")
                if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*", name):
                    return {"type": "tool", "tool": name, "args": arguments}
        except json.JSONDecodeError:
            pass
    if cleaned.startswith("<") or "<|tool_call" in cleaned:
        return {"type": "invalid_action"}
    return None


def response_preview(raw: str, *, structured: bool) -> str:
    """Read only top-level reply fields, including an incomplete JSON string.

    Control actions and reasoning are never sent to the UI token stream.
    """
    cleaned = raw.lstrip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    if not cleaned.startswith("{"):
        if structured or cleaned.startswith(("<", "`", "[")):
            return ""
        return cleaned
    decoder = json.JSONDecoder()
    fields = {}
    position = 1
    while position < len(cleaned):
        tail = cleaned[position:].lstrip()
        position = len(cleaned) - len(tail)
        if tail.startswith(","):
            position += 1
            continue
        try:
            key, end = decoder.raw_decode(cleaned, position)
            if not isinstance(key, str):
                break
            position = end
            while position < len(cleaned) and cleaned[position].isspace():
                position += 1
            if position >= len(cleaned) or cleaned[position] != ":":
                break
            position += 1
            while position < len(cleaned) and cleaned[position].isspace():
                position += 1
            try:
                value, position = decoder.raw_decode(cleaned, position)
                fields[key] = value
            except json.JSONDecodeError:
                if key in {"message", "content"} and cleaned[position:position + 1] == '"':
                    fragment = cleaned[position + 1:]
                    # Trim only an unfinished escape (including a split unicode escape).
                    fragment = re.sub(r"\\(?:u[0-9a-fA-F]{0,3})?$", "", fragment)
                    try:
                        fields[key] = json.loads('"' + fragment + '"')
                    except json.JSONDecodeError:
                        pass
                break
        except json.JSONDecodeError:
            break
    if fields.get("type") not in {"reply", "final", "message"}:
        return ""
    text = fields.get("message", fields.get("content", ""))
    if not isinstance(text, str) or "tool_call" in text or text.lstrip().startswith(("{", "<")):
        return ""
    # A surrogate may arrive before the rest of its JSON unicode pair.
    return text.encode("utf-8", errors="replace").decode("utf-8")
