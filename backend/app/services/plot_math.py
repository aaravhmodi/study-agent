"""Evaluate tutor-written plot formulas such as "8 - 4*(x - 2)" without running code.

Formulas are parsed with ``ast`` and only arithmetic, ``x``, a few constants and
whitelisted math functions are accepted; everything else is rejected before any
value is computed. Results are floats, and math errors become NaN (a gap in the plot).
"""

import ast
import math
import re
from collections.abc import Callable

Formula = Callable[[float], float]

MAX_FORMULA_LENGTH = 200

_CONSTANTS: dict[str, float] = {"pi": math.pi, "e": math.e}


def _step(value: float) -> float:
    return 1.0 if value >= 0 else 0.0


def _ramp(value: float) -> float:
    return max(value, 0.0)


_FUNCTIONS: dict[str, Callable[..., float]] = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "exp": math.exp,
    "ln": math.log,
    "log": math.log,
    "log10": math.log10,
    "sqrt": math.sqrt,
    "abs": abs,
    "floor": math.floor,
    "ceil": math.ceil,
    "sign": lambda value: math.copysign(1.0, value) if value else 0.0,
    "min": min,
    "max": max,
    # Heaviside step and Macaulay bracket <x>^1 for singularity functions.
    "step": _step,
    "ramp": _ramp,
}

_BINARY: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a**b,
}

# "2x" and "3(x+1)" are common in tutor output; make the product explicit.
_IMPLICIT_PRODUCT = re.compile(r"((?<![\w.])\d+(?:\.\d+)?|\))\s*(?=[x(])")


class FormulaError(ValueError):
    """A plot formula uses syntax or names outside the allowed set."""


def compile_formula(text: str) -> Formula:
    """Turn a formula in ``x`` into a function, or raise ``FormulaError``."""

    if not text.strip():
        raise FormulaError("empty formula")
    if len(text) > MAX_FORMULA_LENGTH:
        raise FormulaError(f"formula longer than {MAX_FORMULA_LENGTH} characters")
    source = _IMPLICIT_PRODUCT.sub(r"\1*", text.replace("^", "**").replace("·", "*"))
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"cannot read formula {text!r}") from exc
    build = _build(tree.body)

    def evaluate(x: float) -> float:
        try:
            value = float(build(x))
        except (ArithmeticError, ValueError, TypeError):
            return math.nan
        return value if math.isfinite(value) else math.nan

    return evaluate


def _build(node: ast.expr) -> Formula:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int | float):
            raise FormulaError("only numbers are allowed as constants")
        constant = float(node.value)
        return lambda x: constant
    if isinstance(node, ast.Name):
        if node.id == "x":
            return lambda x: x
        if node.id in _CONSTANTS:
            named = _CONSTANTS[node.id]
            return lambda x: named
        raise FormulaError(f"unknown name {node.id!r}")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        operand = _build(node.operand)
        sign = -1.0 if isinstance(node.op, ast.USub) else 1.0
        return lambda x: sign * operand(x)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        operator = _BINARY[type(node.op)]
        left, right = _build(node.left), _build(node.right)
        return lambda x: operator(left(x), right(x))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        function = _FUNCTIONS.get(node.func.id)
        if function is None:
            raise FormulaError(f"unknown function {node.func.id!r}")
        if not node.args:
            raise FormulaError(f"{node.func.id}() needs an argument")
        args = [_build(arg) for arg in node.args]
        return lambda x: function(*(arg(x) for arg in args))
    raise FormulaError(f"unsupported syntax: {type(node).__name__}")
