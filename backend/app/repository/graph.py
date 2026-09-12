"""Repository-level knowledge graph.

Builds a NetworkX multi-digraph over a `RepoAnalysis` with:

- Nodes: file, module, class, function, variable
- Edges:
    DEFINES     module -> function/class (containment)
    IMPORTS     module -> module
    CALLS       function -> function
    INHERITS    class -> class
    DATAFLOW    function -> variable (reads/writes)

Edges carry weights; we provide ARISE-style queries on top, so agents can ask
"What calls this?", "where is this defined?", "what tests exercise this?" etc.
instead of dumping the whole repository into context.
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

from .analyzer import (
    callers_of,
    callees_of,
    modules_depending_on,
    RepoAnalysis,
)


class RepositoryGraph:
    def __init__(self, analysis: RepoAnalysis) -> None:
        self.g: nx.MultiDiGraph = nx.MultiDiGraph()
        self.analysis = analysis
        self._build()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        analysis = self.analysis

        # module / file nodes
        for module, symbols in analysis.modules.items():
            self.g.add_node(module, type="module", file=symbols.module, weight=2)
            file_path = analysis_root_rel(analysis, symbols) if False else None  # noqa: F841
        for fn_q, fn in analysis.functions.items():
            self.g.add_node(fn_q, type="function", file=fn.file, weight=3)
            module = _module_of(fn_q, fn)
            self.g.add_edge(module, fn_q, rel="DEFINES", weight=1)
            if fn.is_method and fn.class_name:
                self.g.add_edge(fn.class_name, fn_q, rel="DEFINES", weight=1)
        for cls_q, cls in analysis.classes.items():
            self.g.add_node(cls_q, type="class", file=cls.file, weight=3)
            module = _module_of(cls_q, cls)
            self.g.add_edge(module, cls_q, rel="DEFINES", weight=1)

        # inheritance
        for cls_q, cls in analysis.classes.items():
            for base in cls.bases:
                target = _resolve_base(base, analysis)
                if target:
                    self.g.add_edge(cls_q, target, rel="INHERITS", weight=1)

        # calls (best-effort leaf resolution)
        for fn_q, fn in analysis.functions.items():
            for call in fn.calls:
                target = _resolve_call(call, fn, analysis)
                if target and target != fn_q:
                    self.g.add_edge(fn_q, target, rel="CALLS", weight=1)

        # imports as edges
        for mod, imports in analysis.imports_by_file.items():
            for imp in imports:
                top = imp.split(".")[0]
                if top in analysis.modules:
                    self.g.add_edge(mod, top, rel="IMPORTS", weight=1)

        # data flow edges: functions that reference variables defined at module
        # level, and variables consumed by a function.
        self._build_dataflow()

    def _build_dataflow(self) -> None:
        analysis = self.analysis
        # index: module-level variable name -> defining function (none -> module)
        vend = {v.name: v for v in analysis.variables if v.kind == "definition"}
        for fn_q, fn in analysis.functions.items():
            src = fn.source
            if not src:
                continue
            for var in _free_names(src):
                if var in vend and vend[var].file == fn.file:
                    self.g.add_edge(fn_q, var, rel="DATAFLOW", weight=1)
            # file-level variables used inside the function counted anyway
            for var in _free_names(src):
                self.g.add_edge(fn_q, var, rel="READS", weight=1)

    # -- serialisation ------------------------------------------------------

    def to_graphml(self, path: Path) -> None:
        nx.write_graphml(self.g, str(path))

    def to_json(self, path: Path | None = None) -> dict:
        data = {
            "nodes": [
                {"id": n, "type": d.get("type", "node"), "file": d.get("file"), "weight": d.get("weight", 1)}
                for n, d in self.g.nodes(data=True)
            ],
            "edges": [
                {"source": u, "target": v, "rel": d.get("rel", "?"), "weight": d.get("weight", 1)}
                for u, v, d in self.g.edges(data=True)
            ],
            "statistics": self.statistics(),
        }
        if path:
            path.write_text(json.dumps(data))
        return data

    def statistics(self) -> dict:
        types = {}
        for _, d in self.g.nodes(data=True):
            t = d.get("type", "node")
            types[t] = types.get(t, 0) + 1
        rels = {}
        for _, _, d in self.g.edges(data=True):
            r = d.get("rel", "?")
            rels[r] = rels.get(r, 0) + 1
        return {
            "n_nodes": self.g.number_of_nodes(),
            "n_edges": self.g.number_of_edges(),
            "node_types": types,
            "edge_relations": rels,
        }

    # -- ARISE-style queries -------------------------------------------------

    def who_calls(self, qualified: str, depth: int = 1) -> list[dict]:
        hits = []
        for level in range(depth):
            callers = callers_of(self.analysis, qualified.split(".")[level] if level == 0 else qualified)
            for c in callers:
                hits.append({"function": c, "depth": level + 1})
        return hits

    def callers(self, qualified: str) -> list[str]:
        return callers_of(self.analysis, qualified)

    def callees(self, qualified: str) -> list[str]:
        return callees_of(self.analysis, qualified)

    def dependents(self, module: str) -> list[str]:
        return modules_depending_on(self.analysis, module)

    def function_definition(self, qualified: str) -> dict | None:
        fn = self.analysis.functions.get(qualified)
        if not fn:
            return None
        return {
            "file": fn.file,
            "start": fn.start,
            "end": fn.end,
            "params": fn.params,
            "source": fn.source,
        }

    def suspicious_function_sources(self, qualified: str) -> str:
        fn = self.analysis.functions.get(qualified)
        if not fn:
            return ""
        return fn.source

    def neighbors(self, node: str) -> list[dict]:
        out = []
        for _, n, d in self.g.out_edges(node, data=True):
            out.append({"target": n, "rel": d.get("rel"), "direction": "out"})
        for n, _, d in self.g.in_edges(node, data=True):
            out.append({"source": n, "rel": d.get("rel"), "direction": "in"})
        return out

    def subgraph_for(self, functions: list[str], depth: int = 1) -> dict:
        """JSON serialisable neighbourhood around selected functions for UI."""
        selected = set(functions)
        include = set(selected)
        for _ in range(depth):
            for f in list(selected):
                include.update(self.g.successors(f))
                include.update(self.g.predecessors(f))
        nodes = [n for n in include if self.g.has_node(n)]
        edges = [
            {"source": u, "target": v, "rel": d.get("rel")}
            for u, v, d in self.g.edges(include, data=True)
            if u in include and v in include
        ]
        return {
            "nodes": [
                {"id": n, "type": self.g.nodes[n].get("type"), "file": self.g.nodes[n].get("file")}
                for n in nodes
            ],
            "edges": edges,
        }


# -- helpers ----------------------------------------------------------------

def _module_of(qualified: str, obj) -> str:  # noqa: ANN001
    """Approximate module container from a qualified name."""
    if hasattr(obj, "is_method") and obj.is_method and getattr(obj, "class_name", None):
        return obj.file.removesuffix(".py").replace("/", ".")
    return obj.file.removesuffix(".py").replace("/", ".")


def _resolve_base(base: str, analysis: RepoAnalysis) -> str | None:
    if base in analysis.classes:
        return base
    # search by leaf name
    leaf = base.split(".")[-1]
    for cls in analysis.classes:
        if cls.split(".")[-1] == leaf:
            return cls
    return None


def _resolve_call(call: str, caller, analysis: RepoAnalysis) -> str | None:
    members = [k for k in analysis.functions if k.split(".")[-1] == call]
    if not members:
        # method calls of form self.xxx won't resolve to module functions
        return None
    if len(members) == 1:
        return members[0]
    # prefer same-file candidate
    for m in members:
        if analysis.functions[m].file == caller.file:
            return m
    return members[0]


def analysis_root_rel(analysis: RepoAnalysis, symbols) -> str:  # noqa: ANN001
    return symbols.module


def _free_names(src: str) -> set[str]:
    """Crude free-identifier extraction (no full static analysis needed here)."""
    import ast as _ast

    names: set[str] = set()
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return names
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Name):
            names.add(node.id)
        elif isinstance(node, _ast.Attribute):
            base = node.value
            chain = []
            while isinstance(base, _ast.Attribute):
                chain.append(base.attr)
                base = base.value
            if isinstance(base, _ast.Name):
                chain.append(base.id)
                names.add(".".join(reversed(chain)))
    return names


def build_graph(analysis: RepoAnalysis) -> RepositoryGraph:
    return RepositoryGraph(analysis)