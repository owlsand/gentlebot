"""LLM routing and observability."""
from __future__ import annotations

import ast
import json
import logging
import math
import os
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Callable

import requests

from .providers.gemini import GeminiClient
from ..infra.retries import call_with_backoff
from ..infra.quotas import QuotaGuard, Limit, RateLimited
from dotenv import load_dotenv

log = logging.getLogger(f"gentlebot.{__name__}")

# Ensure environment variables from a local .env are loaded so the Gemini
# API key is available even when this module is imported before bot_config.
load_dotenv()


SYSTEM_INSTRUCTION = (
    "You are Gentlebot, a Discord copilot/robot for the Gentlefolk community.\n\n"
    "Personality and voice:\n"
    "- Fun but concise and factual. Default to 2-5 sentences.\n"
    "- Friendly but dry. Light touch of humor only if it increases clarity.\n"
    "Interaction rules:\n"
    "- Avoid flooding: keep under ~1200 characters per message when possible.\n"
    "Style constraints:\n"
    "- Present trade-offs and probabilities where relevant.\n\n"
    "Tools:\n"
    "- `web_search(query, max_results?)` — fetch fresh facts from the web when local context is insufficient.\n"
    "- `calculate(expression)` — evaluate math and unit conversions instead of estimating.\n"
    "- `read_file(path, limit?, offset?)` — inspect project files for citations or context; stay within the repo and keep snippets short.\n"
    "Call tools only when needed, summarize their results for the user, and do not invent tool outputs."
)

class SafetyBlocked(Exception):
    """Raised when content is blocked for safety."""


class LLMRouter:
    def __init__(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key is None:
            log.debug("GEMINI_API_KEY environment variable not set")
        self.client = GeminiClient(api_key)
        self.models = {
            "general": os.getenv("MODEL_GENERAL", "gemini-flash-latest"),
            "scheduled": os.getenv("MODEL_SCHEDULED", "gemini-2.5-pro"),
            "image": os.getenv("MODEL_IMAGE", "gemini-2.0-flash-preview-image"),
        }
        def _limit(route: str, default: Limit) -> Limit:
            prefix = f"GEMINI_{route.upper()}_"
            rpm = os.getenv(f"{prefix}RPM")
            tpm = os.getenv(f"{prefix}TPM")
            rpd = os.getenv(f"{prefix}RPD")
            return Limit(
                rpm=int(rpm) if rpm is not None else default.rpm,
                tpm=int(tpm) if tpm is not None else default.tpm,
                rpd=int(rpd) if rpd is not None else default.rpd,
            )

        self.quota = QuotaGuard(
            {
                "general": _limit("general", Limit(rpm=15, tpm=1_000_000, rpd=1_500)),
                "scheduled": _limit("scheduled", Limit(rpm=2, tpm=1_000_000, rpd=1_500)),
                "image": _limit("image", Limit(rpm=10, tpm=1_000_000, rpd=1_500)),
            }
        )
        self.tool_limits = QuotaGuard(
            {
                "web_search": Limit(rpm=5, rpd=250),
                "calculate": Limit(rpm=10, rpd=500),
                "read_file": Limit(rpm=8, rpd=400),
            }
        )
        self.base_dir = Path(os.getenv("GENTLEBOT_ROOT", Path.cwd())).resolve()

    def _tokens_estimate(
        self, messages: List[Dict[str, Any]], system_instruction: str | None = None
    ) -> int:
        count = sum(len(m.get("content", "").split()) for m in messages)
        if system_instruction:
            count += len(system_instruction.split())
        return count

    def _tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "function_declarations": [
                    {
                        "name": "web_search",
                        "description": "Search the public web for up-to-date answers when local knowledge is insufficient.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "keywords or question to search for"},
                                "max_results": {
                                    "type": "integer",
                                    "description": "maximum snippets to return",
                                    "minimum": 1,
                                    "maximum": 5,
                                },
                            },
                            "required": ["query"],
                        },
                    },
                    {
                        "name": "calculate",
                        "description": "Safely evaluate a math expression including unit conversions like percentages.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "expression": {
                                    "type": "string",
                                    "description": "math expression such as '((42 * 1.08) - 5) / 3'",
                                }
                            },
                            "required": ["expression"],
                        },
                    },
                    {
                        "name": "read_file",
                        "description": "Read a short snippet from a project file for citations or extra context.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "relative path inside the repository to read",
                                },
                                "limit": {
                                    "type": "integer",
                                    "description": "maximum number of characters to return",
                                    "minimum": 100,
                                    "maximum": 4000,
                                },
                                "offset": {
                                    "type": "integer",
                                    "description": "character offset to start reading from",
                                    "minimum": 0,
                                    "maximum": 20_000,
                                },
                            },
                            "required": ["path"],
                        },
                    },
                ]
            }
        ]

    def _extract_tool_calls(self, response: Any) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        for candidate in getattr(response, "candidates", []) or []:
            parts = getattr(getattr(candidate, "content", None), "parts", []) or []
            for part in parts:
                func = getattr(part, "function_call", None)
                if not func and isinstance(part, dict):
                    func = part.get("function_call")
                if not func:
                    continue
                name = getattr(func, "name", None) or (func.get("name") if isinstance(func, dict) else None)
                if not name:
                    continue
                args = getattr(func, "args", None) or (func.get("args") if isinstance(func, dict) else None)
                calls.append({"name": name, "args": args or {}})
        return calls

    def _safe_eval(self, expression: str) -> float:
        node = ast.parse(expression, mode="eval")

        allowed_ops = {
            ast.Add: lambda a, b: a + b,
            ast.Sub: lambda a, b: a - b,
            ast.Mult: lambda a, b: a * b,
            ast.Div: lambda a, b: a / b,
            ast.Pow: lambda a, b: a**b,
            ast.Mod: lambda a, b: a % b,
        }
        allowed_unary = {ast.USub: lambda a: -a, ast.UAdd: lambda a: a}
        allowed_funcs: dict[str, Callable[..., float]] = {
            "sqrt": math.sqrt,
            "log": math.log,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "abs": lambda x: float(abs(x)),
            "round": lambda x: float(round(x, 4)),
        }

        def _eval(n: ast.AST) -> float:
            if isinstance(n, ast.Expression):
                return _eval(n.body)
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
                return float(n.value)
            if isinstance(n, ast.BinOp) and type(n.op) in allowed_ops:
                return allowed_ops[type(n.op)](_eval(n.left), _eval(n.right))
            if isinstance(n, ast.UnaryOp) and type(n.op) in allowed_unary:
                return allowed_unary[type(n.op)](_eval(n.operand))
            if isinstance(n, ast.Call):
                func_name = getattr(n.func, "id", None)
                if func_name and func_name in allowed_funcs:
                    fn = allowed_funcs[func_name]
                    return float(fn(*[_eval(arg) for arg in n.args]))
            raise ValueError("Unsupported expression")

        return _eval(node)

    def _tool_handlers(self) -> dict[str, Callable[[dict[str, Any]], str]]:
        return {
            "web_search": self._run_search,
            "calculate": self._run_calculate,
            "read_file": self._run_read_file,
        }

    def _run_search(self, params: dict[str, Any]) -> str:
        query = str(params.get("query", "")).strip()
        max_results = int(params.get("max_results", 3) or 3)
        if not query:
            raise ValueError("query is required")
        max_results = max(1, min(max_results, 5))

        def _from_google() -> list[str]:
            api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
            search_engine = os.getenv("GOOGLE_SEARCH_CX")
            if not api_key or not search_engine:
                return []

            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "q": query,
                    "key": api_key,
                    "cx": search_engine,
                    "num": max_results,
                    "safe": "active",
                },
                timeout=8,
            )
            resp.raise_for_status()
            payload = resp.json()

            results: list[str] = []
            for item in payload.get("items", []) or []:
                title = re.sub(r"\s+", " ", (item.get("title") or "").strip())
                snippet = re.sub(r"\s+", " ", (item.get("snippet") or "").strip())
                link = item.get("link")
                parts = [part for part in (title, snippet, link) if part]
                if parts:
                    results.append(" — ".join(parts))
            return results

        def _from_duckduckgo() -> list[str]:
            resp = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_redirect": 1, "no_html": 1},
                timeout=8,
            )
            resp.raise_for_status()
            payload = resp.json()
            results: list[str] = []
            abstract = payload.get("AbstractText")
            if abstract:
                results.append(str(abstract))
            for topic in payload.get("RelatedTopics", []):
                text = topic.get("Text") or topic.get("Result")
                if text:
                    results.append(str(text))
                if len(results) >= max_results:
                    break
            return results

        def _from_jina_markdown(url: str) -> list[str]:
            try:
                resp = requests.get(
                    f"https://r.jina.ai/{url}", params={"q": query}, timeout=8
                )
                resp.raise_for_status()
            except requests.HTTPError as exc:
                status = getattr(exc.response, "status_code", None)
                log.warning(
                    "tool=web_search status=jina_error url=%s code=%s query=%s",
                    url,
                    status,
                    query,
                )
                return []

            text = resp.text
            marker = "Markdown Content:"
            if marker in text:
                text = text.split(marker, 1)[1]
            lines = [line.strip() for line in text.splitlines()]
            entries: list[list[str]] = []
            current: list[str] | None = None
            for line in lines:
                if not line or line.startswith("About "):
                    continue
                if line.startswith("-") or line.startswith("="):
                    continue
                match = re.match(r"^(\d+)\.\s+(.*)$", line)
                link_match = re.match(r"^\[(.+?)\]\((https?://[^\)]+)\)$", line)
                if match:
                    if current:
                        entries.append(current)
                    current = [re.sub(r"\s+", " ", match.group(2)).strip()]
                    continue
                if link_match:
                    if current:
                        entries.append(current)
                    title = re.sub(r"\s+", " ", link_match.group(1)).strip()
                    url_text = link_match.group(2).strip()
                    current = [title, url_text]
                    continue
                if current is not None and not line.startswith("--"):
                    snippet = re.sub(r"\s+", " ", line).strip()
                    if snippet:
                        current.append(snippet)
            if current:
                entries.append(current)
            return [" ".join(entry).strip() for entry in entries]

        def _from_duckduckgo_markdown() -> list[str]:
            return _from_jina_markdown("http://duckduckgo.com/html/")

        def _from_google_markdown() -> list[str]:
            return _from_jina_markdown("http://www.google.com/search")

        results = []
        try:
            results = _from_google()
        except Exception:
            log.exception("tool=web_search status=google_error query=%s", query)

        if not results:
            try:
                results = _from_google_markdown()
            except Exception:
                log.exception("tool=web_search status=google_markdown_error query=%s", query)

        if not results:
            try:
                results = _from_duckduckgo()
            except Exception:
                log.exception("tool=web_search status=duckduckgo_error query=%s", query)

        if not results:
            try:
                results = _from_duckduckgo_markdown()
            except Exception:
                log.exception("tool=web_search status=duckduckgo_markdown_error query=%s", query)

        if not results:
            return "No search results found."
        return "\n".join(results[:max_results])

    def _run_calculate(self, params: dict[str, Any]) -> str:
        expression = str(params.get("expression", "")).strip()
        if not expression:
            raise ValueError("expression is required")
        value = self._safe_eval(expression)
        return f"{value}"

    def _run_read_file(self, params: dict[str, Any]) -> str:
        rel_path = Path(str(params.get("path", "")).strip())
        limit = int(params.get("limit", 1200) or 1200)
        offset = int(params.get("offset", 0) or 0)
        limit = max(100, min(limit, 4000))
        offset = max(0, min(offset, 20_000))
        if not rel_path:
            raise ValueError("path is required")
        target = (self.base_dir / rel_path).resolve()
        if not str(target).startswith(str(self.base_dir)):
            raise ValueError("path must stay within the repository")
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(str(rel_path))
        data = target.read_text(encoding="utf-8", errors="ignore")
        if offset >= len(data):
            return ""
        return data[offset : offset + limit]

    def _invoke_tool(
        self, name: str | None, args: dict[str, Any], handlers: dict[str, Callable[[dict[str, Any]], str]]
    ) -> str:
        if not name or name not in handlers:
            log.warning("tool=%s status=unknown args=%s", name, args)
            return "Tool not recognized"

        tokens = len(json.dumps(args, default=str).split())
        try:
            self.tool_limits.check(name, tokens)
        except RateLimited:
            log.info("tool=%s status=rate_limited args=%s", name, args)
            return "Tool temporarily rate limited"

        handler = handlers[name]
        try:
            result = handler(args)
            log.info("tool=%s status=ok args=%s", name, args)
            return result
        except Exception as exc:  # pragma: no cover - observability
            log.exception("tool=%s status=error args=%s", name, args)
            return f"Tool failed: {exc}" 

    def generate(
        self,
        route: str,
        messages: List[Dict[str, Any]],
        temperature: float = 0.6,
        think_budget: int = 0,
        json_mode: bool = False,
        system_instruction: str | None = None,
    ) -> str:
        """Send a chat prompt to Gemini and optionally handle tool calls.

        Tool invocations are rate limited separately from model quotas and any
        tool outputs are echoed back into the chat history before asking the
        model for a final response. A small retry loop allows the model to chain
        multiple tools while still honoring the scheduled-route fallbacks.
        """
        model = self.models.get(route)
        if not model:
            raise ValueError(f"unknown route {route}")

        tool_handlers = self._tool_handlers()
        tool_schemas = self._tool_schemas() if not json_mode else None
        current_messages = list(messages)

        def _log_response(tokens_in: int, tokens_out: int, start: float, status: str, block: Any = None):
            total_ms = (time.time() - start) * 1000
            log.info(
                "route=%s model=%s tokens_in=%s tokens_out=%s ttfb_ms=0 total_ms=%s status=%s block_reason=%s",
                route,
                model,
                tokens_in,
                tokens_out,
                int(total_ms),
                status,
                block,
            )

        for attempt in range(3):
            system_prompt = system_instruction or SYSTEM_INSTRUCTION
            tokens_in = self._tokens_estimate(current_messages, system_prompt)
            allow_fallback = route == "scheduled" and attempt == 0
            try:
                temp_delta = self.quota.check(route, tokens_in)
            except RateLimited:
                if allow_fallback:
                    log.info(
                        "route=%s model=%s tokens_in=%s status=rate_limited fallback=general",
                        route,
                        model,
                        tokens_in,
                    )
                    return self.generate(
                        "general",
                        current_messages,
                        temperature,
                        think_budget,
                        json_mode,
                        system_instruction=system_prompt,
                    )
                raise
            temp = max(0.0, temperature + temp_delta)
            start = time.time()

            def _call():
                try:
                    return self.client.generate(
                        model=model,
                        messages=current_messages,
                        temperature=temp,
                        json_mode=json_mode,
                        thinking_budget=think_budget,
                        system_instruction=system_prompt,
                        tools=tool_schemas,
                    )
                except TypeError as exc:
                    if "tools" in str(exc):  # backward compatibility with test shims
                        return self.client.generate(
                            model=model,
                            messages=current_messages,
                            temperature=temp,
                            json_mode=json_mode,
                            thinking_budget=think_budget,
                            system_instruction=system_prompt,
                        )
                    raise

            try:
                resp = call_with_backoff(_call)
            except RateLimited:
                if allow_fallback:
                    log.info(
                        "route=%s model=%s tokens_in=%s status=rate_limited fallback=general",
                        route,
                        model,
                        tokens_in,
                    )
                    return self.generate(
                        "general",
                        current_messages,
                        temperature,
                        think_budget,
                        json_mode,
                        system_instruction=system_prompt,
                    )
                log.info(
                    "route=%s model=%s tokens_in=%s status=rate_limited", route, model, tokens_in
                )
                raise
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if allow_fallback and (status == 429 or (status and 500 <= status < 600)):
                    log.warning(
                        "route=%s model=%s tokens_in=%s status=%s fallback=general",
                        route,
                        model,
                        tokens_in,
                        status,
                    )
                    return self.generate(
                        "general",
                        current_messages,
                        temperature,
                        think_budget,
                        json_mode,
                        system_instruction=system_prompt,
                    )
                log.exception(
                    "route=%s model=%s tokens_in=%s status=error", route, model, tokens_in
                )
                raise

            tokens_out = getattr(
                getattr(resp, "usage_metadata", None), "candidates_token_count", 0
            )
            tool_calls = self._extract_tool_calls(resp) if tool_schemas else []
            text = getattr(resp, "text", "")
            block_reason = getattr(resp, "prompt_feedback", None)

            if tool_calls:
                _log_response(tokens_in, tokens_out, start, "tool_call", block_reason)
                tool_feedback: list[dict[str, str]] = []
                for call in tool_calls:
                    name = call.get("name")
                    args = call.get("args") or {}
                    result = self._invoke_tool(name, args, tool_handlers)
                    tool_feedback.append(
                        {
                            "role": "assistant",
                            "content": f"Calling {name} with {json.dumps(args)}",
                        }
                    )
                    tool_feedback.append(
                        {
                            "role": "user",
                            "content": f"Tool {name} result: {result}",
                        }
                    )
                current_messages = current_messages + tool_feedback
                continue

            status = "ok" if text else "blocked"
            _log_response(tokens_in, tokens_out, start, status, block_reason)
            if not text:
                raise SafetyBlocked
            return text

        raise RuntimeError("LLM tool loop exceeded attempts")

    def generate_image(self, prompt: str) -> bytes | None:
        model = self.models.get("image")
        if not model:
            raise ValueError("image model not configured")
        tokens_in = len(prompt.split())
        self.quota.check("image", tokens_in)
        start = time.time()

        def _call():
            return self.client.generate_image(model=model, prompt=prompt)

        try:
            resp = call_with_backoff(_call)
        except RateLimited:
            log.info("route=image model=%s tokens_in=%s status=rate_limited", model, tokens_in)
            raise
        except Exception:
            log.exception(
                "route=image model=%s tokens_in=%s status=error", model, tokens_in
            )
            raise

        data = None
        try:
            # Gemini responses may include textual parts before the actual
            # image data. Walk through all returned parts and capture the
            # final ``inline_data`` block as the effective image result.
            parts = resp.candidates[0].content.parts  # type: ignore[attr-defined]
            for part in parts:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    data = inline.data
        except Exception:
            data = None
        total_ms = (time.time() - start) * 1000
        log.info(
            "route=image model=%s tokens_in=%s tokens_out=0 ttfb_ms=0 total_ms=%s status=%s block_reason=%s",
            model,
            tokens_in,
            int(total_ms),
            "ok" if data else "error",
            None,
        )
        if data:
            return data
        return None


router = LLMRouter()
