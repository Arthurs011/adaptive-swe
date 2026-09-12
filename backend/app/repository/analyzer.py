"""Python-repository analysis.

Parses the repository with Python's AST and produces a structured index of
modules, functions, classes, call relationships, variable definitions/uses and
test files. This mirrors (in spirit) the repository-level reasoning ARISE
provides while keeping a self-contained implementation.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
    "node_modules", ".tox", "dist", "build", ".mypy_cache", ".pytest_cache",
    "site-packages", ".eggs", "migrations_dead",
}
EXCLUDE_FILES = {".DS_Store"}

TEST_FILE_RE = re.compile(r"(^|[/_])(test|tests)_|(_test)\.py$", re.IGNORECASE)


@dataclass
class FunctionInfo:
    name: str
    qualified: str
    file: str
    start: int
    end: int
    params: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)  # called function names (local resolution best-effort)
    decorators: list[str] = field(default_factory=list)
    is_method: bool = False
    class_name: str | None = None
    source: str = ""


@dataclass
class ClassInfo:
    name: str
    qualified: str
    file: str
    start: int
    end: int
    bases: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    source: str = ""


@dataclass
class VariableInfo:
    name: str
    qualified: str
    file: str
    line: int
    kind: str  # definition | use
    function: str | None = None


@dataclass
class FileSymbols:
    module: str
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    assignments: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class RepoAnalysis:
    root: Path
    files: list[Path] = field(default_factory=list)
    py_files: list[Path] = field(default_factory=list)
    test_files: list[Path] = field(default_factory=list)
    modules: dict[str, FileSymbols] = field(default_factory=dict)
    functions: dict[str, FunctionInfo] = field(default_factory=dict)  # qualified -> info
    classes: dict[str, ClassInfo] = field(default_factory=dict)
    variables: list[VariableInfo] = field(default_factory=list)
    imports_by_file: dict[str, list[str]] = field(default_factory=dict)


def _module_for_file(root: Path, path: Path) -> str:
    rel = path.relative_to(root)
    parts = list(rel.parts)
    if parts and parts[-1] in {"__init__.py", "__main__.py"}:
        parts = parts[:-1]
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def _collect(py_files: list[Path]) -> RepoAnalysis:
    return RepoAnalysis(root=Path("."), py_files=py_files)


def analyze_repository(root: Path) -> RepoAnalysis:
    analysis = RepoAnalysis(root=root)

    for path in sorted(root.rglob("*.py")):
        if any(part in EXCLUDE_DIRS for part in path.relative_to(root).parts):
            continue
        analysis.py_files.append(path)
        if TEST_FILE_RE.search(str(path.relative_to(root))):
            analysis.test_files.append(path)

    for path in analysis.py_files:
        module = _module_for_file(root, path)
        symbols = _parse_file(path, module, root, analysis)
        analysis.modules[module] = symbols
        for fn in symbols.functions:
            analysis.functions[fn.qualified] = fn
        for cls in symbols.classes:
            analysis.classes[cls.qualified] = cls
        analysis.variables.extend(symbols.assignments and [])
        analysis.imports_by_file[module] = symbols.imports

    _resolve_calls(analysis)
    return analysis


class _FunctionVisitor(ast.NodeVisitor):
    def __init__(self, file: str, module: str, root: Path) -> None:  # noqa: ARG002
        self.file = file
        self.module = module
        self.functions: list[FunctionInfo] = []
        self.classes: list[ClassInfo] = []
        self.scope_stack: list[str] = []

    def _qual(self, name: str) -> str:
        parts = list(self.scope_stack) + [name]
        return ".".join(parts)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._make_function(node, is_method=False)
        self.generic_visit_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._make_function(node, is_method=False)
        self.generic_visit_scope(node)

    def _make_function(self, node, is_method: bool):  # noqa: ANN001
        class_name = self.scope_stack[-1] if self.scope_stack else None
        info = FunctionInfo(
            name=node.name,
            qualified=self._qual(node.name),
            file=self.file,
            start=node.lineno,
            end=getattr(node, "end_lineno", node.lineno),
            params=[a.arg for a in node.args.args],
            decorators=[self._dec_name(d) for d in node.decorator_list if self._dec_name(d)],
            is_method=is_method,
            class_name=class_name,
            source=ast.get_source_segment(_src_of(node), node) or "",
        )
        self.functions.append(info)
        return info

    def generic_visit_scope(self, node: ast.AST) -> None:  # noqa: ANN001
        self.scope_stack.append(node.name)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef):
                self.visit_FunctionDef(child)
            elif isinstance(child, ast.AsyncFunctionDef):
                self.visit_AsyncFunctionDef(child)
            elif isinstance(child, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                self.scope_stack_children = self.scope_stack[:]
                self.generic_visit(child)
            else:
                self.generic_visit(child)
        self.scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        qual = self._qual(node.name)
        self.classes.append(
            ClassInfo(
                name=node.name,
                qualified=qual,
                file=self.file,
                start=node.lineno,
                end=getattr(node, "end_lineno", node.lineno),
                bases=[self._name(b) for b in node.bases],
                methods=[],
                source=ast.get_source_segment(_src_of(node), node) or "",
            )
        )
        self.scope_stack.append(node.name)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = self._make_function(child, is_method=True)
                self.classes[-1].methods.append(fn.qualified)
        self.scope_stack.pop()

    @staticmethod
    def _name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parts = []
            cur = node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            return ".".join(reversed(parts))
        return ast.unparse(node) if hasattr(ast, "unparse") else ""

    @staticmethod
    def _dec_name(node: ast.AST) -> str | None:
        if isinstance(node, (ast.Name,)):
            return node.id
        if isinstance(node, ast.Attribute):
            return _FunctionVisitor._name(node)
        if isinstance(node, ast.Call):
            return _FunctionVisitor._name(node.func)
        return None


def _src_of(node: ast.AST) -> str:
    # fallback source holder; replaced by caller using the real file contents
    return getattr(node, "_src", "")


class _CallVisitor(ast.NodeVisitor):
    """Collect the names of functions called inside one function body."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        name = _FunctionVisitor._name(node.func)
        if name:
            self.calls.append(name)
        self.generic_visit(node)


def _parse_file(path: Path, module: str, root: Path, analysis: RepoAnalysis) -> FileSymbols:
    source = path.read_text(encoding="utf-8", errors="replace")
    file_str = str(path.relative_to(root))
    symbols = FileSymbols(module=module)

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return symbols

    class _ImportVisitor(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
            for a in node.names:
                symbols.imports.append(a.name)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
            base = node.module or ""
            for a in node.names:
                symbols.imports.append(f"{base}.{a.name}")

    fv = _FunctionVisitor(file_str, module, root)
    # give source to AST nodes for get_source_segment
    for node in ast.walk(tree):
        setattr(node, "_src", source)
    fv.visit(tree)
    symbols.functions = fv.functions
    symbols.classes = fv.classes

    iv = _ImportVisitor()
    iv.visit(tree)

    # top-level variable definitions
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                analysis.variables.append(
                    VariableInfo(
                        name=_FunctionVisitor._name(t) if isinstance(t, ast.Name) else "",
                        qualified=_FunctionVisitor._name(t) if isinstance(t, ast.Name) else "",
                        file=file_str,
                        line=node.lineno,
                        kind="definition",
                    )
                )

    return symbols


def _resolve_calls(analysis: RepoAnalysis) -> None:
    """Attach call lists to functions (best-effort, no type resolution)."""
    for fn_key, fn in analysis.functions.items():
        src = fn.source
        if not src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        cv = _CallVisitor()
        cv.visit(tree)
        fn.calls = cv.calls


# ---------------------------------------------------------------------------
# Query helpers the agents use instead of dumping raw repo text.
# ---------------------------------------------------------------------------

def callers_of(analysis: RepoAnalysis, qualified: str) -> list[str]:
    """Which functions call this function (qualified or by leaf name)?"""
    leaf = qualified.split(".")[-1]
    matches: list[str] = []
    for fn_key, fn in analysis.functions.items():
        if leaf in fn.calls or qualified in fn.calls:
            matches.append(fn_key)
    return matches


def callees_of(analysis: RepoAnalysis, qualified: str) -> list[str]:
    fn = analysis.functions.get(qualified)
    if not fn:
        return []
    return list(fn.calls)


def functions_in_file(analysis: RepoAnalysis, file: Path | str) -> list[str]:
    return [k for k, v in analysis.functions.items() if v.file == str(file)]


def tests_for_function(analysis: RepoAnalysis, qualified: str) -> list[str]:
    """Find test files that reference the function name."""
    leaf = qualified.split(".")[-1]
    hits: list[str] = []
    for t in analysis.test_files:
        try:
            text = t.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if leaf in text:
            hits.append(str(t))
    return hits


def modules_depending_on(analysis: RepoAnalysis, module: str) -> list[str]:
    deps: list[str] = []
    for mod, imp in analysis.imports_by_file.items():
        if mod == module:
            continue
        for i in imp:
            if i == module or i.startswith(module + "."):
                deps.append(mod)
                break
    return deps


def search_symbols(analysis: RepoAnalysis, term: str) -> list[str]:
    """Return qualified symbols whose name contains `term` (case-insensitive)."""
    t = term.lower()
    return [
        k
        for k in list(analysis.functions) + list(analysis.classes)
        if t in k.lower()
    ]