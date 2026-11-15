"""Count how often each public API entry point is used by demos and by apps.

Two axes, because they answer different questions:

* entry points -- the names in ``console_window.__all__``.  A reference is an
  AST load (``Name``/``Attribute``) or a ``from console_window import ...``
  alias, so comments, docstrings and help strings are not counted.
* methods -- public methods that are defined on exactly one exported class, so
  ``.set()`` or ``.get()`` are skipped rather than attributed to an arbitrary
  owner.  Only call sites (``obj.method(...)``) are counted, and only when the
  handle is known to hold that owner: from an annotated parameter or attribute,
  from an exported constructor, or from a function whose return annotation names
  the class.  A handle the file never types falls back to :data:`RECEIVERS`.

The report also lists the names the demos never use but an application does,
with the number of applications and the busiest one, because "one import" and
"one application depends on it" are different findings.

Sibling applications live one directory up.  Their ``.venv``/``build``/``dist``
trees contain *installed copies of this library*, so counting those would score
the library's own source as application usage; they are excluded.

Run as a script to regenerate ``docs/API-USAGE.md``::

    python tests/api_usage_report.py --write docs/API-USAGE.md
"""

from __future__ import annotations

import argparse
import ast
import importlib
from pathlib import Path

ClassDef = ast.ClassDef

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / 'demos'
SIBLING_ROOT = ROOT.parent

# Vendored installs, build sandboxes and VCS metadata: never application code.
EXCLUDED_PARTS = ('.venv', 'site-packages', '/build/', '/dist/', '/.git/',
                  'node_modules', '.tox', '__pycache__')


def public_names() -> list[str]:
    """The package's public surface, as an ordered list."""
    pkg = importlib.import_module('console_window')
    return sorted(pkg.__all__)


#: Receivers that unambiguously hold a library object when nothing in the file
#: says otherwise.  A call is attributed only through one of these, through an
#: exported class name, or through a handle inferred from an annotation or a
#: constructor, so ``rows.pop()`` does not land in ``ScreenStack.pop``'s column.
RECEIVERS = frozenset({
    'win', 'window', 'screen', 'help_screen', 'stack', 'spinner', 'spins', 'spin',
    'opts', 'theme', 'glyphs', 'appearance', 'header', 'line', 'prompt',
    'editor', 'bar', 'menu', 'spins_obj', 'app',
})


def method_owners() -> dict[str, str]:
    """Public methods defined on exactly one exported class, name -> owner."""
    pkg = importlib.import_module('console_window')
    owners: dict[str, set[str]] = {}
    for name in pkg.__all__:
        obj = getattr(pkg, name)
        if not isinstance(obj, type):
            continue
        for attr in vars(obj):
            if not attr.startswith('_'):
                owners.setdefault(attr, set()).add(name)
    return {method: next(iter(names)) for method, names in owners.items()
            if len(names) == 1}


def python_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.rglob('*.py')
                  if not any(part in str(path) for part in EXCLUDED_PARTS))


def imports_library(files: list[Path]) -> bool:
    """True when any file imports the package, at any depth."""
    for path in files:
        try:
            tree = ast.parse(path.read_text(errors='ignore'))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if (node.module or '').split('.')[0] == 'console_window':
                    return True
            elif isinstance(node, ast.Import):
                if any(alias.name.split('.')[0] == 'console_window'
                       for alias in node.names):
                    return True
    return False


def count_tree(files: list[Path], names: set[str]) -> dict[str, int]:
    """Reference counts for *names* across *files*, ignoring text and comments."""
    # Sorted, so equal scores keep a stable order across processes (string
    # hashing is randomized, and a set would reorder ties between runs).
    counts = dict.fromkeys(sorted(names), 0)
    for path in files:
        try:
            tree = ast.parse(path.read_text(errors='ignore'))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id in counts:
                    counts[node.id] += 1
            elif isinstance(node, ast.Attribute):
                if node.attr in counts:
                    counts[node.attr] += 1
            elif isinstance(node, ast.ImportFrom):
                if (node.module or '').split('.')[0] == 'console_window':
                    for alias in node.names:
                        if alias.name in counts:
                            counts[alias.name] += 1
    return counts


def _receiver_name(node: ast.expr) -> str | None:
    """The handle a call goes through: ``win`` for ``win.add_body(...)``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _annotation_owners(node: ast.expr | None, entries: set[str]) -> set[str]:
    """Exported class names mentioned anywhere in an annotation expression."""
    if node is None:
        return set()
    found: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in entries:
            found.add(sub.id)
        elif isinstance(sub, ast.Attribute) and sub.attr in entries:
            found.add(sub.attr)
    return found


def return_owners(files: list[Path], entries: set[str]) -> dict[str, set[str]]:
    """``function name -> exported classes`` from return annotations.

    This is what types ``spin = self.new_spinner()`` when ``new_spinner()`` is
    declared ``-> OptionSpinner``: the call site has no annotation of its own.
    """
    result: dict[str, set[str]] = {}
    for path in files:
        try:
            tree = ast.parse(path.read_text(errors='ignore'))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found = _annotation_owners(node.returns, entries)
                if found:
                    result.setdefault(node.name, set()).update(found)
    return result


def _value_owners(value: ast.expr | None, entries: set[str],
                  returns: dict[str, set[str]],
                  class_map: dict[str, set[str]]) -> set[str]:
    """Exported classes a right-hand side can produce."""
    if not isinstance(value, ast.Call):
        return set()
    func = value.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, 'attr', '')
    if name in entries:
        return {name}
    if name in class_map:
        # A subclass constructor: the handle holds the exported base's API.
        return set(class_map[name])
    if isinstance(func, ast.Attribute):
        return set(returns.get(name, ()))
    return set()


def handle_owners(tree: ast.Module, entries: set[str],
                  returns: dict[str, set[str]],
                  class_map: dict[str, set[str]]) -> dict[str, set[str]]:
    """``handle -> exported classes`` as declared in one file.

    Sources are annotated parameters (``win: ConsoleWindow``), annotated
    attributes (``self.bar: IncrementalSearchBar``), and assignments from an
    exported constructor, a subclass constructor, or a call whose return
    annotation names an exported class.
    """
    handles: dict[str, set[str]] = {}

    def note(target: ast.expr, owners: set[str]) -> None:
        name = _receiver_name(target)
        if name and name not in ('self', 'cls') and owners:
            handles.setdefault(name, set()).update(owners)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = node.args
            every = list(arguments.posonlyargs) + list(arguments.args)
            every += list(arguments.kwonlyargs)
            if arguments.vararg is not None:
                every.append(arguments.vararg)
            if arguments.kwarg is not None:
                every.append(arguments.kwarg)
            for arg in every:
                note(ast.Name(id=arg.arg, ctx=ast.Load()),
                     _annotation_owners(arg.annotation, entries))
        elif isinstance(node, ast.AnnAssign):
            note(node.target,
                 _annotation_owners(node.annotation, entries)
                 or _value_owners(node.value, entries, returns, class_map))
        elif isinstance(node, ast.Assign):
            owners = _value_owners(node.value, entries, returns, class_map)
            for target in node.targets:
                note(target, owners)
    return handles


def _classes(tree: ast.Module) -> dict[str, ClassDef]:
    return {node.name: node for node in ast.walk(tree)
            if isinstance(node, ClassDef)}


def class_roots(files: list[Path], roots: set[str]) -> dict[str, set[str]]:
    """``class name -> exported ancestors`` for the classes in *files*.

    Only classes that inherit, directly or not, from an exported class appear.
    Two consumers: ``self`` inside such a class *is* the library object (so
    ``self.add_body(...)`` counts), and a handle built from such a constructor
    holds that base class's API (``self.info = InfoScreen(app)`` where
    ``InfoScreen(BasicTextScreen)``).
    """
    bases: dict[str, set[str]] = {}
    for path in files:
        try:
            tree = ast.parse(path.read_text(errors='ignore'))
        except SyntaxError:
            continue
        for name, node in _classes(tree).items():
            bases.setdefault(name, set()).update(
                base.attr if isinstance(base, ast.Attribute) else getattr(base, 'id', '')
                for base in node.bases)
    resolved: dict[str, set[str]] = {name: parents & roots
                                     for name, parents in bases.items()}
    changed = True
    while changed:
        changed = False
        for name, parents in bases.items():
            inherited: set[str] = set()
            for parent in parents:
                inherited |= resolved.get(parent, set())
            if not inherited <= resolved.setdefault(name, set()):
                resolved[name] |= inherited
                changed = True
    return {name: found for name, found in resolved.items() if found}


def derived_classes(files: list[Path], roots: set[str]) -> set[str]:
    """Class names that inherit, directly or not, from an exported class."""
    return set(class_roots(files, roots)) - roots


def _attributed(handle: str | None, owner: str, by_owner: dict[str, set[str]],
                generic: set[str], self_allowed: bool) -> bool:
    """True when *handle* may be holding an instance of *owner*."""
    if handle is None:
        return False
    if handle in by_owner.get(owner, ()):
        return True
    if handle in generic:
        return True
    return bool(self_allowed and handle == 'self')


def _by_owner(handles: dict[str, set[str]]) -> dict[str, set[str]]:
    """Invert ``handle -> classes`` into ``class -> handles``."""
    inverted: dict[str, set[str]] = {}
    for handle, own in handles.items():
        for owner in own:
            inverted.setdefault(owner, set()).add(handle)
    return inverted


def _is_super_call(node: ast.expr) -> bool:
    """True for ``super()``: inside a derived class that is still ``self``."""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == 'super')


def _scan_nodes(nodes: list[ast.AST], counts: dict[str, int],
                owners: dict[str, str], by_owner: dict[str, set[str]],
                generic: set[str], self_allowed: bool) -> None:
    """Add the attributed calls under *nodes* to *counts*."""
    for root in nodes:
        for node in ast.walk(root):
            if (not isinstance(node, ast.Call)
                    or not isinstance(node.func, ast.Attribute)):
                continue
            method = node.func.attr
            if method not in counts:
                continue
            handle = _receiver_name(node.func.value)
            if handle is None and self_allowed and _is_super_call(node.func.value):
                handle = 'self'
            if _attributed(handle, owners[method], by_owner, generic, self_allowed):
                counts[method] += 1


def count_calls(files: list[Path], methods: set[str], owners: dict[str, str],
                receivers: set[str], derived: set[str], entries: set[str],
                class_map: dict[str, set[str]]) -> dict[str, int]:
    """Attributed call-site counts (``receiver.method(...)``) across *files*.

    A call counts when its handle is declared to hold the owning class in that
    file, when the handle is one of :data:`RECEIVERS` and the file says nothing
    about it, when the handle is an exported class name (classmethods), or when
    it is ``self`` inside a class that descends from an exported class.  Without
    that restriction the common method names would be swamped by unrelated code;
    with the owner check, a pre-3.0 ``window.add_body()`` is not credited to
    ``Screen.add_body``.
    """
    counts = dict.fromkeys(sorted(methods), 0)
    returns = return_owners(files, entries)

    for path in files:
        try:
            tree = ast.parse(path.read_text(errors='ignore'))
        except SyntaxError:
            continue
        handles = handle_owners(tree, entries, returns, class_map)
        by_owner = _by_owner(handles)
        generic = {name for name in receivers if name not in handles}
        for node in tree.body:
            if not isinstance(node, ClassDef):
                _scan_nodes([node], counts, owners, by_owner, generic, False)
            else:
                _scan_nodes([node], counts, owners, by_owner, generic,
                            node.name in derived)
    return counts


def gather() -> dict[str, object]:
    """Every number the report needs, with the file sets it was computed from."""
    demo_files = python_files(DEMO_DIR)
    apps: dict[str, list[Path]] = {}
    for directory in sorted(SIBLING_ROOT.iterdir()):
        if not directory.is_dir() or directory == ROOT:
            continue
        files = python_files(directory)
        if files and imports_library(files):
            apps[directory.name] = files

    entry_names = set(public_names())
    owners = method_owners()
    method_names = set(owners)
    receivers = set(RECEIVERS) | entry_names
    all_files = demo_files + [path for files in apps.values() for path in files]
    class_map = class_roots(all_files, entry_names)
    derived = set(class_map) - entry_names

    demo_entries = count_tree(demo_files, entry_names)
    app_entries = dict.fromkeys(sorted(entry_names), 0)
    demo_methods = count_calls(demo_files, method_names, owners, receivers,
                               derived, entry_names, class_map)
    app_methods = dict.fromkeys(sorted(method_names), 0)
    per_app: dict[str, int] = {}
    entries_by_app: dict[str, dict[str, int]] = {}
    methods_by_app: dict[str, dict[str, int]] = {}

    for app_name, app_files in apps.items():
        entries = count_tree(app_files, entry_names)
        methods = count_calls(app_files, method_names, owners, receivers,
                              derived, entry_names, class_map)
        per_app[app_name] = sum(entries.values()) + sum(methods.values())
        entries_by_app[app_name] = entries
        methods_by_app[app_name] = methods
        for name, value in entries.items():
            app_entries[name] += value
        for name, value in methods.items():
            app_methods[name] += value

    return {
        'demo_files': demo_files,
        'apps': apps,
        'demo_entries': demo_entries,
        'app_entries': app_entries,
        'demo_methods': demo_methods,
        'app_methods': app_methods,
        'entries_by_app': entries_by_app,
        'methods_by_app': methods_by_app,
        'owners': owners,
        'per_app': per_app,
    }


def _row(*cells: object) -> str:
    return '| ' + ' | '.join(str(cell) for cell in cells) + ' |'


def _zero_demo_rows(names: list[str], demo_counts: dict[str, int],
                    by_app: dict[str, dict[str, int]]) -> list[tuple[str, int, int, str]]:
    """``(name, apps, busiest count, busiest app)`` for names no demo uses.

    Sorted busiest first, so a name one application leans on is not ranked
    below a name three applications merely import.
    """
    rows: list[tuple[str, int, int, str]] = []
    for name in names:
        if demo_counts[name]:
            continue
        users = [(app, counts[name]) for app, counts in by_app.items() if counts[name]]
        if not users:
            continue
        busiest_app, busiest = max(users, key=lambda item: item[1])
        rows.append((name, len(users), busiest, busiest_app))
    rows.sort(key=lambda row: (-row[2], row[0]))
    return rows


def render(data: dict[str, object]) -> str:
    """The markdown report, stable across runs (no timestamps)."""
    demo_entries = data['demo_entries']
    app_entries = data['app_entries']
    demo_methods = data['demo_methods']
    app_methods = data['app_methods']
    entries_by_app = data['entries_by_app']
    methods_by_app = data['methods_by_app']
    owners = data['owners']
    apps = data['apps']
    per_app = data['per_app']

    lines = [
        '# Public API usage',
        '',
        'How much of the public surface the demo suite and the sibling',
        'applications actually touch.  Regenerate with',
        '`python tests/api_usage_report.py --write docs/API-USAGE.md`.',
        '',
        'A *reference* is an AST load of the name (or a `from console_window',
        'import ...` alias).  Comments, docstrings and help text are not counted.',
        'Build metadata, virtualenvs and `build/`-`dist/` sandboxes are excluded:',
        'they hold installed copies of this library, and counting them would score',
        'the library against itself.',
        '',
        '## Entry points',
        '',
        '| API | demos | apps |',
        '| --- | ---: | ---: |',
    ]
    ordered = sorted(demo_entries, key=lambda name: -(demo_entries[name] + app_entries[name]))
    for name in ordered:
        lines.append(_row(f'`{name}`', demo_entries[name], app_entries[name]))

    unused = [name for name in ordered
              if demo_entries[name] == 0 and app_entries[name] == 0]
    if unused:
        lines += ['', 'Entry points with no consumers at all: '
                  + ', '.join(f'`{name}`' for name in unused) + '.']

    zero_entries = _zero_demo_rows(ordered, demo_entries, entries_by_app)
    if zero_entries:
        lines += [
            '',
            '### No demo use, some application use',
            '',
            'The coverage question, one row per entry point the demos never touch.',
            '`apps` counts the applications that reference the name at all; `busiest`',
            'is the largest count inside a single application, so `1` (an import)',
            'reads differently from a name one application depends on.',
            '',
            '| API | apps | busiest | application |',
            '| --- | ---: | ---: | --- |',
        ]
        for name, app_count, busiest, busiest_app in zero_entries:
            lines.append(_row(f'`{name}`', app_count, busiest, busiest_app))

    lines += [
        '',
        '## Methods',
        '',
        'Only methods defined on exactly one exported class are listed, and a call',
        'is counted only when the handle is known to hold that class: an annotated',
        'parameter or attribute (`win: ConsoleWindow`), an exported constructor, or',
        'a function whose return annotation names the class (`spin =',
        'self.new_spinner()`).  An untyped handle falls back to the conventional',
        'names (`win`, `screen`, `stack`, `spinner`, `spin`, `opts`, `theme`,',
        '`header`, `line`, `prompt`, `editor`, `bar`, `menu`, `app`), and `self`',
        'counts inside a class that descends from an exported class.  That keeps',
        '`.pop()` on a list out of `ScreenStack.pop` and `.get()` on a dict out of',
        '`Glyphs.get`, and it keeps a pre-3.0 `window.add_body()` out of',
        '`Screen.add_body`.',
        '',
        '| Method | Owner | demos | apps |',
        '| --- | --- | ---: | ---: |',
    ]
    ordered_methods = sorted(demo_methods,
                             key=lambda name: -(demo_methods[name] + app_methods[name]))
    for name in ordered_methods:
        if demo_methods[name] == 0 and app_methods[name] == 0:
            continue
        lines.append(_row(f'`.{name}()`', f'`{owners[name]}`',
                          demo_methods[name], app_methods[name]))

    zero_methods = _zero_demo_rows(ordered_methods, demo_methods, methods_by_app)
    if zero_methods:
        lines += [
            '',
            '### No demo use, some application use',
            '',
            'Same reading as above, for method calls.  A name here is an integration',
            'shape the demo family never exercises.',
            '',
            '| Method | Owner | apps | busiest | application |',
            '| --- | --- | ---: | ---: | --- |',
        ]
        for name, app_count, busiest, busiest_app in zero_methods:
            lines.append(_row(f'`.{name}()`', f'`{owners[name]}`', app_count,
                              busiest, busiest_app))

    lines += [
        '',
        '## Per application',
        '',
        f'{len(apps)} sibling directories import the library; the rest do not.',
        '',
        '| Application | references |',
        '| --- | ---: |',
    ]
    for name in sorted(per_app, key=lambda name: -per_app[name]):
        lines.append(_row(name, per_app[name]))

    lines += [
        '',
        '## Notes',
        '',
        ('- ' + str(len(data['demo_files'])) + ' demo modules and '
         + str(sum(len(files) for files in apps.values()))
         + ' application modules were scanned.'),
        '- Sibling applications pin older releases in their virtualenvs, so a name',
        '  they use may have been renamed or removed since; the counts reflect the',
        '  names as they exist in this tree.',
        '- A count of one is usually an import; a count of many is real use.  The',
        '  ratio between the two columns is the signal worth reading.',
        '- A demo zero with an application count is not automatically a gap.  The',
        '  applications pin older releases, and several still call the pre-3.0',
        '  window-direct API (`win.add_body()`, a window passed where a `Screen` is',
        '  wanted); those call sites are why `docs/DEMO-GAPS.md` checks the site,',
        '  the spread and the replacement path before calling anything missing.',
        '',
    ]
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', metavar='PATH',
                        help='write the report to PATH instead of stdout')
    args = parser.parse_args()

    report = render(gather())
    if args.write:
        target = Path(args.write)
        # Same bytes as stdout, so the checked-in file can be diffed against it.
        target.write_text(report + '\n')
        print(f'wrote {target} ({len(report.splitlines())} lines)')
    else:
        print(report)


if __name__ == '__main__':
    main()
