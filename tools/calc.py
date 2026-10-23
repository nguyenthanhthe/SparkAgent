"""Safe arithmetic evaluator — no eval(), ever.

Expressions are parsed with ``ast`` and interpreted over a whitelist of
node types (numbers, + - * / // % **, unary minus, parentheses, a fixed
math function set, named constants). Operations that could blow up
(huge exponents, deep nesting, non-numeric literals) are rejected before
evaluation.
"""

from __future__ import annotations

import ast
import math
from typing import Any

MAX_INPUT_CHARS = 500
MAX_EXPONENT = 10_000
MAX_RESULT_ABS = 1e308
MAX_TREE_DEPTH = 60

FUNCTIONS: dict[str, Any] = {
    "abs": abs, "round": round, "min": min, "max": max,
    "sqrt": math.sqrt, "cbrt": getattr(math, "cbrt", lambda x: x ** (1 / 3)),
    "log": math.log, "log2": math.log2, "log10": math.log10,
    "exp": math.exp, "floor": math.floor, "ceil": math.ceil,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "factorial": math.factorial, "gcd": math.gcd,
}
CONSTANTS: dict[str, float] = {
    "pi": math.pi, "e": math.e, "tau": math.tau,
    "inf": math.inf,
}

INT_ARG_FUNCS = {"factorial", "gcd"}


class CalcError(ValueError):
    pass


def evaluate(expression: str, variables: dict[str, float] | None = None) -> float:
    if not isinstance(expression, str) or not expression.strip():
        raise CalcError("empty expression")
    if len(expression) > MAX_INPUT_CHARS:
        raise CalcError(f"expression too long (>{MAX_INPUT_CHARS} chars)")
    allowed_vars = dict(CONSTANTS)
    if variables:
        for key, value in variables.items():
            if not key.isidentifier():
                raise CalcError(f"invalid variable name {key!r}")
            allowed_vars[key] = float(value)
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalcError(f"syntax error: {exc.msg}") from exc
    except (MemoryError, RecursionError) as exc:
        raise CalcError("expression too complex to parse") from exc
    _check_depth(tree)
    result = _eval_node(tree.body, allowed_vars)
    if isinstance(result, complex):
        raise CalcError("complex results are not supported")
    if not math.isfinite(result):
        raise CalcError("result is not finite (overflow or NaN)")
    if abs(result) > MAX_RESULT_ABS:
        raise CalcError("result magnitude out of range")
    return result


def _check_depth(tree: ast.AST) -> None:
    def walk(node: ast.AST, depth: int) -> None:
        if depth > MAX_TREE_DEPTH:
            raise CalcError("expression nesting too deep")
        for child in ast.iter_child_nodes(node):
            walk(child, depth + 1)
    walk(tree, 0)


def _eval_node(node: ast.AST, env: dict[str, Any]) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value,
                                                          (int, float)):
            raise CalcError(f"literal {node.value!r} is not a number")
        return float(node.value)

    if isinstance(node, ast.Name):
        if node.id not in env:
            raise CalcError(f"unknown name {node.id!r} "
                            f"(allowed: {sorted(env)})")
        return float(env[node.id])

    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, env)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
        raise CalcError("unsupported unary operator")

    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, env)
        right = _eval_node(node.right, env)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise CalcError("division by zero")
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            if right == 0:
                raise CalcError("division by zero")
            return left // right
        if isinstance(node.op, ast.Mod):
            if right == 0:
                raise CalcError("modulo by zero")
            return left % right
        if isinstance(node.op, ast.Pow):
            if abs(right) > MAX_EXPONENT:
                raise CalcError(f"exponent |{right:g}| exceeds "
                                f"{MAX_EXPONENT}")
            return left ** right
        raise CalcError("unsupported binary operator")

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or \
                node.func.id not in FUNCTIONS:
            name = getattr(node.func, "id", "<expr>")
            raise CalcError(f"function {name!r} is not allowed "
                            f"(allowed: {sorted(FUNCTIONS)})")
        if node.keywords:
            raise CalcError("keyword arguments are not allowed")
        args = [_eval_node(arg, env) for arg in node.args]
        if node.func.id in INT_ARG_FUNCS:   # math.factorial/gcd need ints
            args = [int(arg) if isinstance(arg, float) and arg.is_integer()
                    else arg for arg in args]
        try:
            result = FUNCTIONS[node.func.id](*args)
        except (ValueError, TypeError, OverflowError,
                ZeroDivisionError) as exc:
            raise CalcError(f"{node.func.id}({', '.join(map(str, args))}) "
                            f"failed: {exc}") from exc
        try:
            return float(result)
        except (TypeError, OverflowError, ValueError) as exc:
            raise CalcError(f"{node.func.id} returned non-numeric "
                            f"result {result!r}") from exc

    raise CalcError(f"unsupported syntax: {type(node).__name__}")


def try_evaluate(expression: str) -> dict:
    """Evaluate and return a structured result for tool output."""
    try:
        value = evaluate(expression)
    except CalcError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "value": value,
            "rounded": round(value, 10)}
