"""Everything that talks to Claude: photo reading, the streamed summary, and the tool-using chat agent.

Every public function fails soft by raising AIUnavailable with a message the UI can show.
"""

from __future__ import annotations

import base64
import inspect
import json
import os
from contextlib import contextmanager
from typing import Any, Callable, Iterator

MODEL = os.environ.get("HEALTHCHECK_MODEL", "claude-opus-5-5")
MAX_TOOL_ROUNDS = 8
# Server-side refusal fallback (beta). Set HEALTHCHECK_FALLBACKS=0 to send plain requests.
USE_FALLBACKS = os.environ.get("HEALTHCHECK_FALLBACKS", "1") != "0"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

PHOTO_PROMPT = (
    "This photo was taken by someone checking their food and medicines. It may show pill "
    "bottles, medicine boxes, a prescription list, a meal, a menu, an ingredient label, or a "
    "product barcode.\n"
    "- medications: generic drug names you can actually read on a label or list. Convert a "
    "legible brand name to its generic name. Never guess a medication from the shape or colour "
    "of a pill or package; if the name is not legible, leave it out.\n"
    "- foods: foods clearly visible in a meal, and foods or ingredients legibly printed on a "
    "menu or ingredient label.\n"
    "- barcode: the digits printed under a barcode if every digit is legible, otherwise an "
    "empty string.\n"
    "- notes: one short sentence on what the photo shows and anything you could not read.\n"
    "List only what is legible or clearly visible. Empty lists are a correct answer."
)

PHOTO_SCHEMA = {
    "type": "object",
    "properties": {
        "medications": {"type": "array", "items": {"type": "string"}},
        "foods": {"type": "array", "items": {"type": "string"}},
        "barcode": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["medications", "foods", "barcode", "notes"],
    "additionalProperties": False,
}

EXPLAIN_SYSTEM = (
    "You write the result summary shown to a consumer in HealthCheckup, an app that scans a "
    "food or medicine, checks recall databases, and maps how foods affect medicines through "
    "shared proteins.\n"
    "You are given JSON with three parts: product, recalls, interactions. Use ONLY that data; "
    "add no facts from memory.\n"
    "Cover, in plain language: what the product is; whether a recall matched and what to do "
    "about it (a match on barcode, lot or NDC is this exact product; a name match is only a "
    "possible match to compare against the package); then each food-drug interaction as "
    "food -> protein -> drug, what it means, and what to do.\n"
    "If the data shows no interaction, say that no interaction was found in the sources "
    "checked. Likewise for recalls: say no recall was found in the sources that answered, and "
    "name any source that did not answer. Never say the product is safe.\n"
    "Name the source for each claim (for example CPSC, FDA label, Open Targets), taken from "
    "the data.\n"
    "Stay under 180 words. Plain text, short lines, no headings. End with one line telling the "
    "user to confirm with a pharmacist."
)

CHAT_SYSTEM = (
    "You are HealthCheckup's assistant. HealthCheckup helps people check a food, supplement or "
    "medicine for recalls and understand how foods affect their medicines at the protein level "
    "(food component -> protein <- drug).\n"
    "Always use the tools for facts about recalls, drug targets and food-drug interactions "
    "rather than your memory; if a tool returns an error or a source did not answer, say so "
    "plainly. Typical order: identify the product, check recalls, then check interactions with "
    "the user's medicines.\n"
    "Cite which source each fact came from, using the source names in the tool results.\n"
    "When no recall or interaction is found, say none was found in the sources checked; do not "
    "call anything safe.\n"
    "Explain an interaction as a path: the food and its active component, the protein it "
    "acts on, the drug that depends on that protein, what that means, and what to do.\n"
    "Keep answers short and in plain language. This is information, not medical advice: "
    "suggest confirming with a pharmacist or doctor when a decision depends on it."
)

TOOL_INPUTS: dict[str, dict] = {
    "lookup_barcode": {
        "type": "object",
        "properties": {"barcode": {"type": "string", "description": "UPC/EAN/GTIN digits"}},
        "required": ["barcode"],
        "additionalProperties": False,
    },
    "check_recalls": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Product or generic drug name"},
            "kind": {"type": "string", "enum": ["food", "drug", "other", "unknown"]},
            "brand": {"type": "string", "description": "Brand, if known"},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
    "drug_targets": {
        "type": "object",
        "properties": {"drug": {"type": "string", "description": "Generic or brand drug name"}},
        "required": ["drug"],
        "additionalProperties": False,
    },
    "food_drug_interactions": {
        "type": "object",
        "properties": {
            "food": {"type": "string", "description": "Food name or ingredient list"},
            "drugs": {"type": "array", "items": {"type": "string"}, "description": "Drug names"},
        },
        "required": ["food", "drugs"],
        "additionalProperties": False,
    },
    "local_health_briefing": {
        "type": "object",
        "properties": {"state": {"type": "string", "description": "Two-letter US state code"}},
        "required": ["state"],
        "additionalProperties": False,
    },
}

_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_api_key: str | None = None


class AIUnavailable(Exception):
    """Claude could not be used; str(exc) is safe to show to the user."""


def configure(api_key: str | None) -> None:
    """Store an API key supplied by the web app (for example from Streamlit secrets)."""
    global _api_key
    _api_key = (api_key or "").strip() or None


def available() -> bool:
    return bool(_api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _client():
    """Build the Anthropic client. Tests monkeypatch this."""
    import anthropic

    return anthropic.Anthropic(api_key=_api_key) if _api_key else anthropic.Anthropic()


def _get_client():
    if not available():
        raise AIUnavailable("Claude is not configured: add an Anthropic API key to enable AI features.")
    try:
        return _client()
    except Exception as exc:
        raise AIUnavailable(f"Could not start the Claude client: {exc}") from exc


def _api(client):
    """The messages resource and the extra kwargs for it (beta + refusal fallback when enabled)."""
    if USE_FALLBACKS:
        return client.beta.messages, {"betas": [FALLBACK_BETA], "fallbacks": "default"}
    return client.messages, {}


@contextmanager
def _guard():
    """Translate SDK errors into AIUnavailable, most specific first."""
    import anthropic

    try:
        yield
    except AIUnavailable:
        raise
    except anthropic.AuthenticationError as exc:
        raise AIUnavailable("Claude rejected the API key. Check the key in the app settings.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise AIUnavailable("This API key is not allowed to use the requested Claude model.") from exc
    except anthropic.NotFoundError as exc:
        raise AIUnavailable(f"Claude model '{MODEL}' was not found.") from exc
    except anthropic.BadRequestError as exc:
        raise AIUnavailable(f"Claude rejected the request: {exc.message}") from exc
    except anthropic.RateLimitError as exc:
        raise AIUnavailable("Claude is rate limited right now. Try again in a minute.") from exc
    except anthropic.APIStatusError as exc:
        raise AIUnavailable(f"Claude returned an error ({exc.status_code}). Try again shortly.") from exc
    except anthropic.APIConnectionError as exc:
        raise AIUnavailable("Could not reach Claude. Check the internet connection.") from exc
    except anthropic.AnthropicError as exc:
        raise AIUnavailable(f"Claude is unavailable: {exc}") from exc


def _check_stop(message, what: str) -> None:
    if message.stop_reason == "refusal":
        raise AIUnavailable(f"Claude declined to {what}.")
    if message.stop_reason == "max_tokens":
        raise AIUnavailable(f"Claude ran out of room while trying to {what}.")


def read_photo(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """Read medications, foods and a printed barcode number from a photo."""
    client = _get_client()
    if media_type not in _IMAGE_TYPES:
        raise AIUnavailable(f"Unsupported image type '{media_type}'. Use JPEG, PNG, GIF or WebP.")
    if not image_bytes:
        raise AIUnavailable("The photo is empty.")
    data = base64.standard_b64encode(image_bytes).decode("utf-8")
    with _guard():
        api, extra = _api(client)
        message = api.create(
            model=MODEL,
            max_tokens=8000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": PHOTO_SCHEMA}},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                        {"type": "text", "text": PHOTO_PROMPT},
                    ],
                }
            ],
            **extra,
        )
    _check_stop(message, "read this photo")
    text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise AIUnavailable("Claude's reading of the photo could not be parsed.") from exc
    return {
        "medications": [str(m) for m in parsed.get("medications", [])],
        "foods": [str(f) for f in parsed.get("foods", [])],
        "barcode": "".join(ch for ch in str(parsed.get("barcode", "")) if ch.isdigit()),
        "notes": str(parsed.get("notes", "")),
    }


def explain(product: dict, recalls: dict, interactions: dict) -> Iterator[str]:
    """Stream a short plain-language summary of a scan result. Raises AIUnavailable."""
    client = _get_client()
    payload = json.dumps({"product": product, "recalls": recalls, "interactions": interactions}, default=str)
    return _explain_stream(client, payload)


def _explain_stream(client, payload: str) -> Iterator[str]:
    with _guard():
        api, extra = _api(client)
        with api.stream(
            model=MODEL,
            max_tokens=16000,
            system=EXPLAIN_SYSTEM,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": "Scan result data:\n" + payload}],
            **extra,
        ) as stream:
            for text in stream.text_stream:
                yield text
            message = stream.get_final_message()
    _check_stop(message, "summarise this result")


def _tool_specs() -> list[dict]:
    from healthcheck import tools

    return [
        {
            "name": name,
            "description": inspect.getdoc(fn) or name,
            "input_schema": TOOL_INPUTS[name],
            "eager_input_streaming": True,
        }
        for name, fn in tools.TOOLS.items()
    ]


def _valid_input(name: str, args: Any) -> bool:
    """Eager input streaming skips server-side validation, so check the input here."""
    schema = TOOL_INPUTS.get(name)
    if schema is None or not isinstance(args, dict):
        return False
    props = schema["properties"]
    if any(key not in args for key in schema["required"]) or any(key not in props for key in args):
        return False
    for key, value in args.items():
        if props[key]["type"] == "array":
            if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
                return False
        elif not isinstance(value, str):
            return False
    return True


def _run_tool(name: str, args: Any) -> tuple[str, bool]:
    from healthcheck import tools

    if name not in tools.TOOLS:
        return json.dumps({"error": f"unknown tool '{name}'"}), True
    if not _valid_input(name, args):
        return json.dumps({"INVALID_JSON": json.dumps(args, default=str)}), True
    try:
        result = tools.TOOLS[name](**args)
    except Exception as exc:  # tools should not raise, but never break the loop
        result = {"error": f"{type(exc).__name__}: {exc}"}
    return json.dumps(result, default=str), isinstance(result, dict) and "error" in result


def chat(messages: list[dict], on_tool: Callable[[str, dict], None] | None = None) -> Iterator[str]:
    """Answer a conversation with the tool-using agent, yielding text as it streams.

    messages: [{"role": "user"|"assistant", "content": str}, ...]. on_tool(name, input) is
    called just before each tool runs. Raises AIUnavailable.
    """
    client = _get_client()
    history = [{"role": m["role"], "content": m["content"]} for m in messages if m.get("content")]
    if not history or history[-1]["role"] != "user":
        raise AIUnavailable("Ask a question first.")
    return _chat_stream(client, history, on_tool)


def _chat_stream(client, history: list[dict], on_tool) -> Iterator[str]:
    tool_specs = _tool_specs()
    json_retries = 0
    rounds = 0
    with _guard():
        api, extra = _api(client)
        while True:
            try:
                with api.stream(
                    model=MODEL,
                    max_tokens=64000,
                    system=CHAT_SYSTEM,
                    tools=tool_specs,
                    output_config={"effort": "medium"},
                    messages=history,
                    **extra,
                ) as stream:
                    for event in stream:
                        if event.type == "text":
                            yield event.text
                    response = stream.get_final_message()
                json_retries = 0
            except ValueError as exc:
                # The SDK could not parse a streamed tool input at all: re-issue the turn.
                json_retries += 1
                if json_retries > 2:
                    raise AIUnavailable("Claude produced a tool call that could not be read.") from exc
                continue

            if response.stop_reason == "pause_turn":
                history.append({"role": "assistant", "content": response.content})
                continue
            if response.stop_reason == "refusal":
                raise AIUnavailable("Claude declined to answer this question.")
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                return
            if response.stop_reason == "max_tokens":
                raise AIUnavailable("Claude ran out of room before finishing a tool call.")
            if rounds >= MAX_TOOL_ROUNDS:
                yield "\n\n(Stopped after the maximum number of lookups; ask a narrower question.)"
                return
            rounds += 1

            results = []
            for block in tool_uses:
                if on_tool is not None:
                    try:
                        on_tool(block.name, block.input if isinstance(block.input, dict) else {})
                    except Exception:
                        pass  # a UI callback must not break the answer
                content, is_error = _run_tool(block.name, block.input)
                result = {"type": "tool_result", "tool_use_id": block.id, "content": content}
                if is_error:
                    result["is_error"] = True
                results.append(result)
            history.append({"role": "assistant", "content": response.content})
            history.append({"role": "user", "content": results})  # all results in one message
            yield "\n\n"
