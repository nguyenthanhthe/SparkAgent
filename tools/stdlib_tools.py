"""Standard tool library — registry bindings for the pure tool modules.

Registers: ``calculate``, ``text_analysis``, ``json_query``, ``csv_analyze``,
``statistics``, ``remember``, ``recall_memory``, and ``ask_human``
(approval-queue backed). All handlers validate input with
:mod:`kernel.validation` so malformed model arguments become clean
observations instead of tracebacks.
"""

from __future__ import annotations

import json as json_lib
from typing import Any

from kernel.errors import ToolFailure
from kernel.validation import (require_enum, require_int, require_number,
                               require_str, validate_tool_args)
from security.approval import ApprovalQueue
from tools import calc as calc_mod
from tools import csv_tool as csv_mod
from tools import json_tool as json_mod
from tools import stats_tool as stats_mod
from tools import textops as text_mod
from tools.registry import Tool, ToolContext, ToolRegistry

MAX_TEXT_INPUT = 200_000


def register_tools(registry: ToolRegistry,
                   approvals: ApprovalQueue | None = None) -> None:
    # ------------------------------------------------------------ calculate
    async def calculate(ctx: ToolContext, expression: str) -> dict:
        expression = require_str(expression, "expression", max_len=500)
        return calc_mod.try_evaluate(expression)

    registry.register(Tool(
        name="calculate",
        description=("Evaluate a math expression safely: numbers, + - * / "
                     "// % **, parentheses, functions (abs, round, min, max, "
                     "sqrt, log, log2, log10, exp, floor, ceil, sin, cos, "
                     "tan, factorial, gcd), constants pi/e/tau. Use this "
                     "instead of doing arithmetic in your head."),
        parameters={"expression": {"type": "string", "required": True,
                                   "desc": "e.g. 'sqrt(2) * 10 ** 3'"}},
        handler=calculate))

    # --------------------------------------------------------- text_analysis
    async def text_analysis(ctx: ToolContext, text: str,
                            operation: str = "summary") -> dict:
        text = require_str(text, "text", max_len=MAX_TEXT_INPUT)
        require_enum(operation, "operation",
                     ["summary", "words", "urls", "emails", "dates",
                      "numbers", "slug"])
        if operation == "summary":
            return text_mod.line_summary(text)
        if operation == "words":
            return {"top": text_mod.word_frequencies(text, top=25)}
        if operation == "urls":
            return {"urls": text_mod.extract_urls(text),
                    "domains": text_mod.domains_of(text_mod.extract_urls(text))}
        if operation == "emails":
            return {"emails": text_mod.extract_emails(text)}
        if operation == "dates":
            return {"dates": text_mod.extract_dates(text)}
        if operation == "numbers":
            return {"numbers": text_mod.extract_numbers(text)}
        return {"slug": text_mod.slugify(text)}

    registry.register(Tool(
        name="text_analysis",
        description=("Analyze text: line/word summary, word frequencies, "
                     "extract URLs/emails/dates/numbers, or slugify. "
                     "operation: summary|words|urls|emails|dates|numbers|slug."),
        parameters={"text": {"type": "string", "required": True},
                    "operation": {"type": "string", "required": False}},
        handler=text_analysis))

    # ------------------------------------------------------------ json_query
    async def json_query(ctx: ToolContext, data: str, path: str = "",
                         mode: str = "get", jsonl: bool = False,
                         where: str = "", sort_by: str = "",
                         descending: bool = False,
                         max_depth: int = 0,
                         in_keys: bool = True,
                         in_values: bool = True,
                         default_json: str = "") -> dict:
        data = require_str(data, "data", max_len=MAX_TEXT_INPUT)
        require_enum(mode, "mode",
                     ["get", "search", "shape", "stats", "filter", "sort",
                      "first", "last", "group", "unique", "pluck",
                      "help", "keys"])
        try:
            if jsonl:
                parsed = json_mod.parse_jsonl(data)
            else:
                parsed = json_mod.parse(data)
        except json_lib.JSONDecodeError as exc:
            raise ToolFailure(f"invalid JSON: {exc}") from exc
        except ValueError as exc:
            raise ToolFailure(f"invalid JSONL: {exc}") from exc
        if mode == "get":
            require_str(path, "path", min_len=1)
            try:
                return {"value": json_mod.get_path(parsed, path)}
            except (KeyError, IndexError, TypeError):
                if default_json:
                    try:
                        return {"value": json_mod.parse(default_json),
                                "default_used": True}
                    except json_lib.JSONDecodeError:
                        pass   # fall through to the failure below
                raise ToolFailure(f"path {path!r} failed") from None
        if mode == "search":
            needle = require_str(path, "needle", min_len=1)
            if not in_keys and not in_values:
                raise ToolFailure(
                    "search needs at least one of in_keys/in_values")
            return {"matches": json_mod.search(parsed, needle,
                                               in_keys=in_keys,
                                               in_values=in_values)}
        if mode == "shape":
            depth = max(1, min(int(max_depth), 12)) if max_depth else 4
            return {"shape": json_mod.shape(parsed, max_depth=depth)}
        if mode == "filter":
            where = require_str(where, "where", min_len=1, max_len=500)
            try:
                rows = json_mod.get_path(parsed, path) if path else parsed
            except (KeyError, IndexError, TypeError) as exc:
                raise ToolFailure(f"path {path!r} failed: {exc}") from exc
            if not isinstance(rows, list):
                raise ToolFailure("filter needs a list "
                                  "(use path='items' or jsonl=true)")
            try:
                return {"matches": json_mod.filter_rows(rows, where),
                        "count": len(rows)}
            except ValueError as exc:
                raise ToolFailure(str(exc))
        async def _rows(mode_label: str) -> list:
            """Shared row access for the list modes: dotted path into a
            list, optional `where` filter applied first."""
            try:
                rows = json_mod.get_path(parsed, path) if path else parsed
            except (KeyError, IndexError, TypeError) as exc:
                raise ToolFailure(f"path {path!r} failed: {exc}") from exc
            if not isinstance(rows, list):
                raise ToolFailure(f"{mode_label} needs a list "
                                  "(use path='items' or jsonl=true)")
            if where:
                try:
                    rows = json_mod.filter_rows(rows, where)
                except ValueError as exc:
                    raise ToolFailure(str(exc))
            return rows
        if mode == "sort":
            sort_by = require_str(sort_by, "sort_by", min_len=1, max_len=200)
            return {"value": json_mod.sort_rows(await _rows("sort"),
                                               sort_by,
                                               descending=descending)}
        if mode in ("first", "last"):
            try:
                return {"value": json_mod.first_row(
                    await _rows(mode), where="", last=(mode == "last"))}
            except ValueError as exc:
                raise ToolFailure(str(exc))
        if mode == "group":
            sort_by = require_str(sort_by, "group_by", min_len=1,
                                  max_len=200)
            return {"groups": json_mod.group_rows(await _rows("group"),
                                                  sort_by)}
        if mode == "unique":
            sort_by = require_str(sort_by, "key", min_len=1, max_len=200)
            return {"values": json_mod.unique_values(await _rows("unique"),
                                                     sort_by)}
        if mode == "pluck":
            sort_by = require_str(sort_by, "key", min_len=1, max_len=200)
            return {"values": json_mod.pluck(await _rows("pluck"),
                                             sort_by)}
        if mode == "help":
            return {"where_filter": json_mod.where_help()}
        if mode == "keys":
            # path doubles as the (optional, case-insensitive) prefix
            return {"keys": json_mod.top_keys(parsed, prefix=path)}
        return json_mod.stats(parsed)

    registry.register(Tool(
        name="json_query",
        description=("Inspect JSON: mode=get reads a dotted path "
                     "(e.g. 'items.0.name'; '*' spreads lists/dicts, "
                     "like 'items.*.name'), mode=search finds paths "
                     "containing a needle, mode=shape summarizes structure, "
                     "mode=stats counts keys/leaves, mode=filter keeps "
                     "list rows matching comparison terms in `where` "
                     "(e.g. 'age>=30;status!=done'), and the row modes "
                     "sort/first/last/group/unique/pluck all honor an "
                     "optional `where` filter applied first. "
                     "Set jsonl=true for newline-delimited JSON (treated "
                     "as a list of docs)."),
        parameters={"data": {"type": "string", "required": True,
                             "desc": "raw JSON text"},
                    "path": {"type": "string", "required": False,
                             "desc": "dotted path (get/filter/sort/group) "
                                     "or needle (search)"},
                    "mode": {"type": "string", "required": False},
                    "jsonl": {"type": "boolean", "required": False,
                              "desc": "parse input as JSON lines"},
                    "where": {"type": "string", "required": False,
                              "desc": "filter terms, ';' separated "
                                      "(mode=filter)"},
                    "sort_by": {"type": "string", "required": False,
                                "desc": "row key to sort by (mode=sort)"},
                    "descending": {"type": "boolean", "required": False},
                    "max_depth": {"type": "integer", "required": False,
                                  "desc": "shape mode: recursion limit "
                                          "(1-12, default 4)"},
                    "in_keys": {"type": "boolean", "required": False,
                                "desc": "search mode: match keys "
                                        "(default true)"},
                    "in_values": {"type": "boolean", "required": False,
                                  "desc": "search mode: match string "
                                          "values (default true)"},
                    "default_json": {"type": "string", "required": False,
                                     "desc": "get mode: JSON literal "
                                             "returned (with "
                                             "default_used=true) when "
                                             "the path misses"}},
        handler=json_query))

    # ------------------------------------------------------------- csv_analyze
    async def csv_analyze(ctx: ToolContext, data: str,
                          operation: str = "describe",
                          column: str = "", value: str = "",
                          op: str = "==", group_by: str = "",
                          descending: bool = False,
                          limit: int = 0) -> dict:
        data = require_str(data, "data", max_len=MAX_TEXT_INPUT)
        try:
            table = csv_mod.Table.parse(data)
        except csv_mod.CsvError as exc:
            raise ToolFailure(str(exc)) from exc
        require_enum(operation, "operation",
                     ["describe", "filter", "sort", "aggregate", "group",
                      "head"])
        try:
            if operation == "describe":
                return table.describe()
            if operation == "filter":
                rows = table.filter(column, op, value).head(50)
                if limit:
                    rows = rows[:max(1, min(int(limit), 50))]
                return {"rows": rows}
            if operation == "sort":
                rows = table.sort(column,
                                  descending=descending).head(50)
                if limit:
                    rows = rows[:max(1, min(int(limit), 50))]
                return {"rows": rows}
            if operation == "aggregate":
                return table.aggregate(column)
            if operation == "group":
                return table.group_aggregate(group_by, column)
            # head: caller row count (1-50), default 25
            count = max(1, min(int(limit) if limit else 25, 50))
            return {"rows": table.head(count)}
        except csv_mod.CsvError as exc:
            raise ToolFailure(str(exc)) from exc

    registry.register(Tool(
        name="csv_analyze",
        description=("Analyze CSV text: describe (columns+types), filter "
                     "(column/op/value with == != > < >= <= contains), sort, "
                     "aggregate (sum/avg/min/max of a column), group "
                     "(group_by + column averages), head."),
        parameters={"data": {"type": "string", "required": True},
                    "operation": {"type": "string", "required": False},
                    "column": {"type": "string", "required": False},
                    "value": {"type": "string", "required": False},
                    "op": {"type": "string", "required": False},
                    "group_by": {"type": "string", "required": False},
                    "descending": {"type": "bool", "required": False},
                    "limit": {"type": "integer", "required": False,
                              "desc": "head/filter/sort row count "
                                      "(1-50; head defaults to 25)"}},
        handler=csv_analyze))

    # -------------------------------------------------------------- statistics
    async def statistics(ctx: ToolContext, values: str,
                         operation: str = "summary",
                         values2: str = "", window: int = 3,
                         threshold: float = 3.0) -> dict:
        try:
            numbers = [float(v) for v in require_str(
                values, "values").replace(",", " ").split()]
        except ValueError as exc:
            raise ToolFailure(f"values must be numbers: {exc}") from exc
        require_enum(operation, "operation",
                     ["summary", "quantile", "correlate", "regression",
                      "moving_average", "outliers"])
        try:
            if operation == "summary":
                return stats_mod.summary(numbers)
            if operation == "quantile":
                return {"p25": stats_mod.quantile(numbers, 0.25),
                        "p50": stats_mod.quantile(numbers, 0.5),
                        "p75": stats_mod.quantile(numbers, 0.75)}
            if operation in ("correlate", "regression"):
                others = [float(v) for v in require_str(
                    values2, "values2").replace(",", " ").split()]
                if operation == "correlate":
                    return {"pearson": round(
                        stats_mod.pearson(numbers, others), 6)}
                return stats_mod.linear_regression(numbers, others)
            if operation == "moving_average":
                return {"moving_average": stats_mod.moving_average(
                    numbers, require_int(window, "window", minimum=1))}
            return {"outliers": stats_mod.zscore_outliers(
                numbers, threshold=require_number(
                    threshold, "threshold", minimum=0))}
        except stats_mod.StatsError as exc:
            raise ToolFailure(str(exc)) from exc

    registry.register(Tool(
        name="statistics",
        description=("Statistics over a list of numbers: summary, quantile, "
                     "correlate (needs values2), regression (slope/intercept/"
                     "r2), moving_average (window), outliers (robust z-score)."),
        parameters={"values": {"type": "string", "required": True,
                               "desc": "space- or comma-separated numbers"},
                    "operation": {"type": "string", "required": False},
                    "values2": {"type": "string", "required": False},
                    "window": {"type": "integer", "required": False},
                    "threshold": {"type": "number", "required": False}},
        handler=statistics))

    # ----------------------------------------------------------- memory tools
    async def remember(ctx: ToolContext, text: str, kind: str = "note") -> str:
        text = require_str(text, "text", max_len=8000)
        if ctx.memory is None:
            raise ToolFailure("memory is not available in this context")
        memory_id = await ctx.memory.remember(text, kind=kind)
        return f"stored memory #{memory_id} (kind={kind})"

    registry.register(Tool(
        name="remember",
        description=("Persist a fact, preference, or result into long-term "
                     "memory for future episodes. Use for anything worth "
                     "recalling later."),
        parameters={"text": {"type": "string", "required": True},
                    "kind": {"type": "string", "required": False,
                             "desc": "note|preference|fact|episode"}},
        handler=remember))

    async def recall_memory(ctx: ToolContext, query: str,
                            snippet_width: int = 220) -> dict:
        query = require_str(query, "query")
        if ctx.memory is None:
            raise ToolFailure("memory is not available in this context")
        snippet_width = require_int(snippet_width, "snippet_width",
                                    minimum=40, maximum=1000)
        hits = await ctx.memory.recall(query, k=5,
                                       snippet_width=snippet_width)
        return {"results": [{"kind": h.kind, "text": h.text[:300],
                             "snippet": h.snippet,
                             "score": round(h.score, 3)} for h in hits]}

    registry.register(Tool(
        name="recall_memory",
        description="Semantic search over long-term memory.",
        parameters={"query": {"type": "string", "required": True}},
        handler=recall_memory))

    # -------------------------------------------------------------- ask_human
    async def ask_human(ctx: ToolContext, question: str,
                        detail: str = "") -> str:
        question = require_str(question, "question", max_len=500)
        if approvals is None:
            raise ToolFailure(
                "operator approvals are disabled; proceed with your best "
                "judgment and note the assumption in your final answer")
        request = approvals.submit("question", question,
                                   {"detail": detail[:500],
                                    "episode": ctx.episode_id})
        return (f"Question submitted to the operator (approval id "
                f"{request.id}). Continue with other work if possible; "
                f"the answer will arrive as a future task.")

    registry.register(Tool(
        name="ask_human",
        description=("Ask the operator a question when truly blocked or "
                     "before risky/ambiguous actions. Do not use for things "
                     "you can decide yourself."),
        parameters={"question": {"type": "string", "required": True},
                    "detail": {"type": "string", "required": False}},
        handler=ask_human, dangerous=False))
