from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path


class BundleError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImportedSymbol:
    module: str
    name: str
    asname: str | None


@dataclass(frozen=True)
class ModuleSource:
    module: str
    path: Path
    source: str
    tree: ast.Module


@dataclass(frozen=True)
class SymbolDef:
    name: str
    node: ast.AST
    source: str
    module: str
    lineno: int


def _is_lib_module(module: str | None) -> bool:
    return module is not None and (module == "lib" or module.startswith("lib."))


def _resolve_module_path(module: str, root: Path) -> Path:
    parts = module.split(".")
    file_path = root.joinpath(*parts).with_suffix(".py")
    if file_path.exists():
        return file_path
    pkg_init = root.joinpath(*parts, "__init__.py")
    if pkg_init.exists():
        return pkg_init
    raise BundleError(
        f"module not found: {module!r} (searched {file_path} and {pkg_init})"
    )


def _parse_module_source(module: str, root: Path) -> ModuleSource:
    path = _resolve_module_path(module, root)
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        raise BundleError(f"failed to parse {module!r} at {path}: {e}") from e
    return ModuleSource(module=module, path=path, source=source, tree=tree)


def _extract_top_level_import_lines(mod: ModuleSource) -> tuple[list[str], list[str]]:
    future_imports: list[str] = []
    other_imports: list[str] = []
    for node in mod.tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            seg = ast.get_source_segment(mod.source, node)
            if seg:
                future_imports.append(seg)
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            seg = ast.get_source_segment(mod.source, node)
            if seg:
                other_imports.append(seg)
            continue
    return future_imports, other_imports


def _build_symbol_table(mod: ModuleSource) -> dict[str, ast.AST]:
    table: dict[str, ast.AST] = {}
    for node in mod.tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            table[node.name] = node
            continue
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    table.setdefault(t.id, node)
            continue
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            table.setdefault(node.target.id, node)
            continue
    return table


def _name_loads_in(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            names.add(sub.id)
    return names


def _definition_time_deps(node: ast.AST) -> set[str]:
    context_nodes: list[ast.AST] = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        context_nodes.extend(node.decorator_list)
        for default in node.args.defaults:
            if default is not None:
                context_nodes.append(default)
        for default in node.args.kw_defaults:
            if default is not None:
                context_nodes.append(default)
        for a in (
            list(node.args.posonlyargs)
            + list(node.args.args)
            + list(node.args.kwonlyargs)
        ):
            if a.annotation is not None:
                context_nodes.append(a.annotation)
        if node.args.vararg and node.args.vararg.annotation is not None:
            context_nodes.append(node.args.vararg.annotation)
        if node.args.kwarg and node.args.kwarg.annotation is not None:
            context_nodes.append(node.args.kwarg.annotation)
        if node.returns is not None:
            context_nodes.append(node.returns)
    elif isinstance(node, ast.ClassDef):
        context_nodes.extend(node.decorator_list)
        context_nodes.extend(node.bases)
        context_nodes.extend(node.keywords)
    elif isinstance(node, ast.Assign):
        context_nodes.append(node.value)
    elif isinstance(node, ast.AnnAssign):
        if node.annotation is not None:
            context_nodes.append(node.annotation)
        if node.value is not None:
            context_nodes.append(node.value)
    deps: set[str] = set()
    for c in context_nodes:
        deps |= _name_loads_in(c)
    return deps


def _toposort_symbols(symbols: list[SymbolDef]) -> list[SymbolDef]:
    if not symbols:
        return []

    by_id: dict[str, SymbolDef] = {}
    name_to_first_id: dict[str, str] = {}
    order: list[str] = []
    for s in symbols:
        sid = f"{s.module}:{s.name}:{s.lineno}"
        by_id[sid] = s
        order.append(sid)
        name_to_first_id.setdefault(s.name, sid)

    deps: dict[str, set[str]] = {sid: set() for sid in order}
    indeg: dict[str, int] = {sid: 0 for sid in order}
    for sid in order:
        s = by_id[sid]
        for dep_name in _definition_time_deps(s.node):
            dep_id = name_to_first_id.get(dep_name)
            if dep_id is None or dep_id == sid:
                continue
            if dep_id not in deps[sid]:
                deps[sid].add(dep_id)
                indeg[sid] += 1

    ready = [sid for sid in order if indeg[sid] == 0]
    out: list[str] = []
    ready_set = set(ready)
    while ready:
        # 安定（元の）順序を保つように取り出す
        sid = ready.pop(0)
        ready_set.discard(sid)
        out.append(sid)
        for other in order:
            if sid not in deps[other]:
                continue
            deps[other].remove(sid)
            indeg[other] -= 1
            if indeg[other] == 0 and other not in ready_set and other not in out:
                ready.append(other)
                ready_set.add(other)

    if len(out) != len(order):
        # 循環参照または未解決があるため、元の順序にフォールバックする。
        return symbols
    return [by_id[sid] for sid in out]


def _extract_symbol_def(mod: ModuleSource, name: str, node: ast.AST) -> SymbolDef:
    seg = ast.get_source_segment(mod.source, node)
    if not seg:
        raise BundleError(
            f"failed to extract source for {mod.module}.{name} from {mod.path}"
        )
    lineno = getattr(node, "lineno", 0) or 0
    return SymbolDef(name=name, node=node, source=seg, module=mod.module, lineno=lineno)


def _strip_lib_imports(entry_source: str, entry_tree: ast.Module) -> str:
    lines = entry_source.splitlines(keepends=True)
    remove: list[tuple[int, int]] = []
    for node in entry_tree.body:
        if (
            isinstance(node, ast.ImportFrom)
            and _is_lib_module(node.module)
            and node.level == 0
        ):
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", None) or start
            if start is not None:
                remove.append((start, end))
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
            and node.level == 0
        ):
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", None) or start
            if start is not None:
                remove.append((start, end))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _is_lib_module(alias.name):
                    raise BundleError(
                        "unsupported import form: use 'from lib... import ...' instead of 'import lib...'"
                    )

    to_remove: set[int] = set()
    for start, end in remove:
        for ln in range(start, end + 1):
            to_remove.add(ln)

    kept: list[str] = []
    for i, line in enumerate(lines, start=1):
        if i not in to_remove:
            kept.append(line)
    return "".join(kept).lstrip("\n")


def _comment_block(block: str) -> list[str]:
    out: list[str] = []
    for line in block.splitlines():
        if line.strip() == "":
            out.append("#")
        else:
            out.append("# " + line)
    return out


def _push_region(lines: list[str], name: str) -> None:
    lines.append(f"# region {name}")


def _pop_region(lines: list[str]) -> None:
    lines.append("# endregion")


def _parse_imported_symbols(entry_tree: ast.Module) -> list[ImportedSymbol]:
    imported: list[ImportedSymbol] = []
    for node in entry_tree.body:
        if not (
            isinstance(node, ast.ImportFrom)
            and _is_lib_module(node.module)
            and node.level == 0
        ):
            continue
        if any(a.name == "*" for a in node.names):
            raise BundleError("unsupported import: 'from lib... import *'")
        for a in node.names:
            imported.append(
                ImportedSymbol(module=node.module or "", name=a.name, asname=a.asname)
            )
    return imported


def bundle_file(entry_path: Path, root: Path) -> str:
    entry_source = entry_path.read_text(encoding="utf-8")
    try:
        entry_tree = ast.parse(entry_source, filename=str(entry_path))
    except SyntaxError as e:
        raise BundleError(f"failed to parse entry file {entry_path}: {e}") from e

    imported = _parse_imported_symbols(entry_tree)
    if not imported:
        return entry_source

    entry_lib_imports: list[str] = []
    for node in entry_tree.body:
        if (
            isinstance(node, ast.ImportFrom)
            and _is_lib_module(node.module)
            and node.level == 0
        ):
            seg = ast.get_source_segment(entry_source, node)
            if seg:
                entry_lib_imports.append(seg)

    entry_future_imports: list[str] = []
    for node in entry_tree.body:
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
            and node.level == 0
        ):
            seg = ast.get_source_segment(entry_source, node)
            if seg:
                entry_future_imports.append(seg)

    module_cache: dict[str, ModuleSource] = {}
    symbol_cache: dict[tuple[str, str], SymbolDef] = {}
    module_imports_future: list[str] = []
    module_imports_other: list[str] = []

    def get_module(modname: str) -> ModuleSource:
        if modname not in module_cache:
            mod = _parse_module_source(modname, root)
            fi, oi = _extract_top_level_import_lines(mod)
            module_imports_future.extend(fi)
            module_imports_other.extend(oi)
            module_cache[modname] = mod
        return module_cache[modname]

    included: list[SymbolDef] = []
    included_names: set[str] = set()
    aliases: list[str] = []

    queue: list[ImportedSymbol] = list(imported)
    while queue:
        item = queue.pop(0)
        mod = get_module(item.module)
        table = _build_symbol_table(mod)
        if item.name not in table:
            raise BundleError(
                f"symbol not found: {item.module}.{item.name} (from {mod.path})"
            )
        key = (item.module, item.name)
        sym = symbol_cache.get(key)
        if sym is None:
            sym = _extract_symbol_def(mod, item.name, table[item.name])
            symbol_cache[key] = sym

        if sym.name not in included_names:
            included.append(sym)
            included_names.add(sym.name)

            # 推移的な依存も取り込む（ベストエフォート）。
            for dep in sorted(_name_loads_in(sym.node)):
                if dep in included_names:
                    continue
                if dep in table:
                    queue.append(
                        ImportedSymbol(module=item.module, name=dep, asname=None)
                    )

        if item.asname and item.asname != item.name:
            aliases.append(f"{item.asname} = {item.name}")

    # 定義時依存を考慮しつつ安定な順序にする。
    included = _toposort_symbols(included)

    def _dedup_keep_order(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for it in items:
            key = it.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(it.rstrip())
        return out

    future_imports = _dedup_keep_order(entry_future_imports + module_imports_future)
    other_imports = _dedup_keep_order(module_imports_other)

    # 先頭行に shebang があれば、最初の行として保持する。
    shebang = ""
    entry_lines = entry_source.splitlines(keepends=True)
    if entry_lines and entry_lines[0].startswith("#!"):
        shebang = entry_lines[0].rstrip("\n")

    out: list[str] = []
    if shebang:
        out.append(shebang)

    if entry_lib_imports:
        for seg in entry_lib_imports:
            out.extend(_comment_block(seg))
    out.append("")

    if future_imports or other_imports:
        _push_region(out, "Imports")
        out.extend(future_imports)
        out.extend(other_imports)
        _pop_region(out)
        out.append("")

    current_module: str | None = None
    for sym in included:
        if sym.module != current_module:
            if current_module is not None:
                _pop_region(out)
                out.append("")
            current_module = sym.module
            _push_region(out, current_module)
        out.append(sym.source.rstrip())
        out.append("")
    if current_module is not None:
        _pop_region(out)
        out.append("")

    if aliases:
        _push_region(out, "Aliases")
        out.extend(aliases)
        _pop_region(out)
        out.append("")

    bundled_lib = "\n".join(out).rstrip() + "\n"
    stripped_entry = _strip_lib_imports(entry_source, entry_tree)
    if shebang:
        # すでに出力した場合は、エントリ本体側から shebang を除去する。
        stripped_entry_lines = stripped_entry.splitlines(keepends=True)
        if stripped_entry_lines and stripped_entry_lines[0].startswith("#!"):
            stripped_entry = "".join(stripped_entry_lines[1:]).lstrip("\n")
    entry_body_lines = stripped_entry.rstrip("\n").splitlines()
    return bundled_lib + "\n".join(
        ["", "# region main logic", *entry_body_lines, "", "# endregion", ""]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m lib.bundle",
        description="Bundle lib library imports into a single submission .py file.",
    )
    parser.add_argument("entry", type=Path, help="Entry python file (your solution).")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output file path (default: stdout).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root containing the 'lib/' package (default: auto).",
    )
    args = parser.parse_args(argv)

    try:
        out = bundle_file(args.entry, args.root)
    except BundleError as e:
        parser.error(str(e))
        return 2

    if args.output is None:
        print(out, end="")
    else:
        args.output.write_text(out, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
