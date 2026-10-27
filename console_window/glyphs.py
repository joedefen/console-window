"""Decorative glyphs, and how to live without them.

Every symbol a TUI uses for *meaning* rather than words needs two spellings:
the one the design is built around, and one that a terminal which cannot draw
it (or a font that lacks it) can still show.  A symbol that fails to draw does
not fail loudly -- the terminal paints a box, or nothing -- and the row silently
loses its meaning.  Keeping the symbols in one table matters because the
failure is invisible.

What can and cannot be checked
------------------------------
Whether a terminal can *encode* UTF-8 is observable: the output stream's
encoding and ``TERM`` say so.  Whether the *font* has a glyph for a code point
is not observable from inside the process.  So detection is split three ways:

* :func:`terminal_report` reports what is detectable and sets
  ``ascii_required`` only when UTF-8 output is impossible;
* that report always carries a *font check* line containing the real glyphs, so
  the user can look at them and judge;
* :func:`set_ascii` forces the fallback for everything else, including a font
  the check cannot see.

Degrading for free
------------------
Registering a glyph feeds two consumers: :func:`get` (named lookup) and
:func:`transliterate` (a longest-match substitution applied to whatever text
the app passes to the window).  An app that upgrades this library and changes
nothing gets every *known* decorative code point downgraded as the window
draws; an app that registers its own vocabulary gets its own fallbacks.

Substitution only ever rewrites code points that are registered as decoration:
a pager showing ``GRUB_CMDLINE_LINUX="Grüße"`` is byte-identical in both modes,
because ``ü`` is not in the table.  Set ``CONSOLE_WINDOW_GLYPH_AUDIT=1`` to log
each unseen decorative code point together with the :func:`register` call that
would teach the library about it.
"""

from __future__ import annotations

import locale
import logging
import os
import re
import sys
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

logger = logging.getLogger(__name__)

__all__ = [
    'AUDIT_ENV',
    'BUILTIN_GLYPHS',
    'GLYPHS_ENV',
    'Glyph',
    'Glyphs',
    'TerminalReport',
    'apply_policy',
    'ensure_policy',
    'get',
    'is_ascii',
    'probe',
    'probe_text',
    'register',
    'register_many',
    'reset',
    'set_ascii',
    'terminal_report',
    'transliterate',
    'unicode_of',
]

#: Environment variable that pins the glyph mode for apps without argparse
#: (``auto``, ``ascii`` or ``unicode``).  Also the escape hatch for an app whose
#: terminal was detected wrongly.
GLYPHS_ENV = 'CONSOLE_WINDOW_GLYPHS'

#: Environment variable that turns on the "unregistered decoration" audit.
AUDIT_ENV = 'CONSOLE_WINDOW_GLYPH_AUDIT'

#: Terminal types that cannot draw the Unicode set at all.
ASCII_TERMS = frozenset({'dumb'})

#: Terminals that encode UTF-8 but whose default font usually lacks the
#: emoji-style glyphs; the Linux console is the common case.
LIMITED_TERMS = frozenset({'linux', 'cons25'})

#: Unicode categories that are decoration rather than content.  Used only by
#: the audit, to keep prose ("Grüße") out of the report.
_DECORATIVE_CATEGORIES = frozenset({'So', 'Sk', 'Sm'})

_MODE_VALUES = ('auto', 'ascii', 'unicode')

_VARIATION_SELECTORS = ('\ufe0f', '\ufe0e')


@dataclass(frozen=True)
class Glyph:
    """One decorative symbol in both spellings.

    ``ascii`` may be empty: that spells "delete the decoration", which is the
    right answer for a marker whose meaning is already carried by its column.
    """

    unicode: str
    ascii: str

    def __post_init__(self) -> None:
        if not isinstance(self.unicode, str) or not self.unicode:
            raise TypeError(f'Glyph.unicode must be a non-empty str, got {self.unicode!r}')
        if not isinstance(self.ascii, str):
            raise TypeError(f'Glyph.ascii must be a str, got {self.ascii!r}')
        if not self.ascii.isascii():
            raise ValueError(
                f'Glyph.ascii must be plain ASCII (that is the point), got {self.ascii!r}'
            )


#: Glyphs this library draws itself.  An app that changes nothing gets these
#: downgraded automatically when the terminal cannot show them.
BUILTIN_GLYPHS: dict[str, Glyph] = {
    'cursor': Glyph('\u2502', '|'),          # narrow text cursor in widgets
    'cursor_block': Glyph('\u2588', '#'),    # block cursor / caret
    # One cell in both spellings: the choice list indents the other rows by one
    # cell plus a space, so a two-character marker would knock the column out
    # of alignment exactly where the terminal is already struggling.
    'choice': Glyph('\u2b9e', '>'),          # "this choice is the current value"
    'scroll_prev': Glyph('\u25c0', '<'),     # dialog horizontal scroll, left
    'scroll_next': Glyph('\u25b6', '>'),     # dialog horizontal scroll, right
    'alert_up': Glyph('\u25b2', '^'),        # alert "more above"
    'alert_down': Glyph('\u25bc', 'v'),      # alert "more below"
    'nav_prev': Glyph('\u2190', '<-'),       # help legend, "left arrow"
    'nav_next': Glyph('\u2192', '->'),       # help legend, "right arrow"
    'bullet': Glyph('\u00b7', '.'),          # help-list bullet
    'swatch': Glyph('\u2588', '#'),          # theme colour swatch
    # The message-box frame.  `curses.textpad.rectangle()` already draws with
    # ACS line art, but a message box painted by hand needs its own fallback;
    # registering the corners keeps the ASCII mode invariant ("every painted
    # cell is ASCII") true for dialogs too.
    'box_tl': Glyph('\u250c', '+'),
    'box_h': Glyph('\u2500', '-'),
    'box_tr': Glyph('\u2510', '+'),
    'box_v': Glyph('\u2502', '|'),           # also reused by widgets' cursor
    'box_bl': Glyph('\u2514', '+'),
    'box_br': Glyph('\u2518', '+'),
}

#: Glyph names the font check prints, in reading order, when an app registers
#: none of its own.  These are the built-ins a user is most likely to notice.
BUILTIN_PROBE: tuple[str, ...] = (
    'nav_prev', 'nav_next', 'choice', 'cursor', 'cursor_block', 'bullet',
)

_registry: dict[str, Glyph] = {}
_probe: list[str] = []
_ascii_mode = False
#: True once anything (an app option, the CLI helper, or auto-detection) has
#: chosen a mode.  Later auto-detection must not undo that choice, otherwise
#: every new window would re-run the environment probe and silently revert a
#: ``--ascii`` the user asked for.
_decided = False
_table: re.Pattern[str] | None = None
_map: dict[str, str] = {}
_audited: set[str] = set()


def _reset_state() -> None:
    """Restore the built-in table and the Unicode mode (used by :func:`reset`)."""
    global _ascii_mode, _decided, _table  # pylint: disable=global-statement
    _registry.clear()
    _registry.update(BUILTIN_GLYPHS)
    _probe.clear()
    _probe.extend(BUILTIN_PROBE)
    _ascii_mode = False
    _decided = False
    _table = None
    _map.clear()
    _audited.clear()


def register(name: str, unicode_text: str, ascii_text: str, *, probe: bool = False) -> None:
    """Teach the library one decorative glyph.

    *ascii_text* must be plain ASCII (it may be empty).  ``probe=True`` adds the
    glyph to the font check, where the user sees the real Unicode form.
    """
    global _table  # pylint: disable=global-statement
    if not isinstance(name, str) or not name:
        raise TypeError(f'glyph name must be a non-empty str, got {name!r}')
    _registry[name] = Glyph(unicode_text, ascii_text)
    if probe:
        _add_probe(name)
    _table = None


def register_many(
    mapping: Mapping[str, Glyph | tuple[str, str] | list[str]],
    *,
    probe: Iterable[str] = (),
) -> None:
    """Register a whole table at once.

    Values may be :class:`Glyph` instances or two-item ``(unicode, ascii)``
    sequences.  *probe* names the entries the font check should print, in order.
    """
    for name, spec in mapping.items():
        if isinstance(spec, Glyph):
            unicode_text, ascii_text = spec.unicode, spec.ascii
        elif isinstance(spec, (tuple, list)) and len(spec) == 2:
            unicode_text, ascii_text = spec
        else:
            raise TypeError(
                f'glyph {name!r} must be a Glyph or a (unicode, ascii) pair, '
                f'got {spec!r}'
            )
        register(name, unicode_text, ascii_text)
    for name in probe:
        _add_probe(name)


def _add_probe(name: str) -> None:
    if name not in _registry:
        raise KeyError(f'cannot probe unregistered glyph {name!r}')
    if name not in _probe:
        _probe.append(name)


def probe(*names: str) -> None:
    """Add already-registered glyphs to the font check, in the given order."""
    for name in names:
        _add_probe(name)


def reset() -> None:
    """Drop every app registration and return to the Unicode built-ins.

    This is a test hook: the glyph mode is process state, so a suite must be
    able to start each case from a known state.
    """
    _reset_state()


def get(name: str) -> str:
    """Return glyph *name* in the active set."""
    try:
        glyph = _registry[name]
    except KeyError as exc:
        raise KeyError(f'unknown glyph {name!r}') from exc
    return glyph.ascii if _ascii_mode else glyph.unicode


def unicode_of(name: str) -> str:
    """Return glyph *name* in its Unicode form, whatever the active mode is."""
    try:
        return _registry[name].unicode
    except KeyError as exc:
        raise KeyError(f'unknown glyph {name!r}') from exc


def is_ascii() -> bool:
    """True when the plain-ASCII fallback is in use."""
    return _ascii_mode


def set_ascii(enabled: bool) -> None:
    """Select the plain-ASCII glyph set (True) or the Unicode one (False).

    This is an explicit decision: later auto-detection leaves it alone.
    """
    global _ascii_mode, _decided  # pylint: disable=global-statement
    _ascii_mode = bool(enabled)
    _decided = True


def probe_text() -> str:
    """The real Unicode glyphs a user should look at (never the ASCII set).

    The font check has to print the glyph that might be missing; printing the
    fallback would check nothing.
    """
    shown: list[str] = []
    for name in _probe:
        glyph = _registry.get(name)
        if glyph is None or glyph.unicode in shown:
            continue
        shown.append(glyph.unicode)
    return ' '.join(shown)


def _spellings(text: str) -> list[str]:
    """Every form of *text* an app might have typed, most specific first.

    A glyph is often written with a variation selector (``⚠️``) and just as
    often without (``⚠``); both must map to the same fallback, and both must
    consume the selector so no orphan zero-width mark is left behind.
    """
    forms = [text]
    for selector in _VARIATION_SELECTORS:
        if selector in text:
            forms.append(text.replace(selector, ''))
        else:
            forms.append(text + selector)
    return forms


def _compile_table() -> re.Pattern[str] | None:
    """Build (and cache) the longest-match substitution pattern."""
    global _table  # pylint: disable=global-statement
    if _table is not None:
        return _table
    for glyph in _registry.values():
        if glyph.unicode.isascii():
            continue
        for form in _spellings(glyph.unicode):
            if form.isascii():
                continue
            _map.setdefault(form, glyph.ascii)
    if not _map:
        return None
    alternation = '|'.join(
        re.escape(form) for form in sorted(_map, key=len, reverse=True)
    )
    _table = re.compile(alternation)
    return _table


def _audit_enabled() -> bool:
    raw = os.environ.get(AUDIT_ENV, '')
    return raw.strip().lower() not in ('', '0', 'no', 'false', 'off')


def _suggest_name(ch: str) -> str:
    name = unicodedata.name(ch, 'glyph').lower()
    cleaned = re.sub(r'[^a-z0-9]+', '_', name).strip('_')
    return cleaned[:32] or 'glyph'


def _audit(text: str) -> None:
    """Log decoration that has no fallback, once per code point."""
    for ch in text:
        if ch.isascii() or ch in _VARIATION_SELECTORS or ch in _audited:
            continue
        code = ord(ch)
        decorative = unicodedata.category(ch) in _DECORATIVE_CATEGORIES
        if not (decorative or 0x2500 <= code <= 0x2BFF or 0x1F000 <= code <= 0x1FAFF):
            continue
        _audited.add(ch)
        logger.warning(
            'glyph audit: %r (U+%04X) has no ASCII fallback; teach it with '
            'Glyphs.register(%r, %r, <%r>)',
            ch, code, _suggest_name(ch), ch, 'ascii form',
        )


def transliterate(text: str) -> str:
    """Replace registered Unicode glyphs with their ASCII forms.

    Every other code point is left alone, so content (a hostname, a UTF-8 file
    body, a non-English value) is never rewritten.  In Unicode mode this is the
    identity function and returns *text* itself.
    """
    if not text or not _ascii_mode or text.isascii():
        return text
    table = _compile_table()
    if table is None:
        return text
    result = table.sub(lambda match: _map[match.group(0)], text)
    if _audit_enabled():
        _audit(result)
    return result


@dataclass(frozen=True)
class TerminalReport:
    """What could be learned about this terminal's glyph support."""

    encoding: str
    utf8: bool
    term: str
    ascii_required: bool
    notes: tuple[str, ...] = ()
    ascii_mode: bool = False
    source: str = 'auto'


def _normalized(encoding: str | None) -> str:
    return (encoding or '').strip().lower().replace('-', '').replace('_', '')


def _is_utf8(encoding: str | None) -> bool:
    """True for the UTF-8 family (``utf-8``, ``UTF8``, ``utf_8``, ...)."""
    name = _normalized(encoding)
    return name.startswith('utf8') or name == 'utf'


def terminal_report(
    environ: Mapping[str, str] | None = None,
    stream: object = None,
) -> TerminalReport:
    """Describe this terminal's ability to draw the UI's symbols.

    *environ* and *stream* exist so tests can supply a fake terminal.  The
    result is advisory except for ``ascii_required``, which is True only when
    the terminal provably cannot carry the glyphs (non-UTF-8 output encoding, or
    ``TERM=dumb``).  A font's coverage cannot be observed, so the font-check
    note asks the user to look instead.
    """
    env = os.environ if environ is None else environ
    out = sys.stdout if stream is None else stream
    encoding = getattr(out, 'encoding', None) or locale.getpreferredencoding(False) or ''
    term = str(env.get('TERM', '')).strip().lower()
    notes: list[str] = []

    utf8 = _is_utf8(encoding)
    if not utf8:
        notes.append(
            f'output encoding is {encoding or "unknown"}, which cannot show the '
            'symbols this program draws; using ASCII symbols instead'
        )
    if term in ASCII_TERMS:
        notes.append(f'TERM={term} cannot draw the symbols; using ASCII symbols instead')
    if not utf8 or term in ASCII_TERMS:
        notes.append(
            'for the full symbol set, run in a UTF-8 locale inside a '
            'Unicode-capable terminal'
        )
        return TerminalReport(
            encoding=encoding, utf8=utf8, term=term,
            ascii_required=True, notes=tuple(notes),
        )

    if term in LIMITED_TERMS:
        notes.append(
            f'TERM={term} uses a console font that often lacks some of these '
            'symbols; restart with --ascii if any line shows boxes'
        )
    notes.append(
        f'font check: {probe_text()}  (if any symbol is a box or blank, use --ascii)'
    )
    return TerminalReport(
        encoding=encoding, utf8=utf8, term=term,
        ascii_required=False, notes=tuple(notes),
    )


def _env_mode(env: Mapping[str, str]) -> tuple[str | None, str | None]:
    """Return ``(mode, note)`` for the environment override, if any."""
    raw = str(env.get(GLYPHS_ENV, '')).strip().lower()
    if not raw:
        return None, None
    if raw in _MODE_VALUES:
        return raw, f'glyph mode {raw} from {GLYPHS_ENV}={raw}'
    return None, (
        f'ignoring {GLYPHS_ENV}={raw!r}: expected one of {", ".join(_MODE_VALUES)}'
    )


def _resolve_mode(
    force_ascii: bool | None,
    report: TerminalReport,
    env: Mapping[str, str],
) -> tuple[bool, str, list[str]]:
    """Decide the mode: ``(ascii_mode, source, extra_notes)``."""
    if force_ascii is not None:
        if force_ascii:
            return True, 'request', ['using ASCII symbols (requested)']
        notes = []
        if report.ascii_required:
            notes.append(
                'Unicode symbols requested, but this terminal reports it cannot '
                'show them'
            )
        return False, 'request', notes

    mode, note = _env_mode(env)
    if mode is not None:
        notes = [note] if note else []
        return mode == 'ascii', 'env', notes
    if note is not None:
        notes = [note]
    else:
        notes = []

    auto_ascii = report.ascii_required
    return auto_ascii, 'auto', notes


def apply_policy(
    force_ascii: bool | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stream: object = None,
) -> TerminalReport:
    """Set the process glyph mode and return what was learned.

    Precedence, highest first: *force_ascii* (an app option or ``--ascii``),
    ``CONSOLE_WINDOW_GLYPHS``, then auto-detection.  The returned report's
    ``notes`` are ready to print and its ``ascii_mode``/``source`` say what was
    decided (``'request'``, ``'env'`` or ``'auto'``).
    """
    env = os.environ if environ is None else environ
    report = terminal_report(environ=env, stream=stream)
    ascii_mode, source, extra = _resolve_mode(force_ascii, report, env)
    set_ascii(ascii_mode)
    return replace(
        report,
        notes=tuple(report.notes) + tuple(extra),
        ascii_mode=ascii_mode,
        source=source,
    )


def ensure_policy(
    environ: Mapping[str, str] | None = None,
    stream: object = None,
) -> TerminalReport:
    """Run auto-detection once, unless a mode has already been chosen.

    A window calls this on construction, which is how an app that never thinks
    about glyphs still gets the right mode.  It is deliberately *not* a reset:
    an explicit ``set_ascii()`` (or an earlier ``apply_policy()``) wins for the
    rest of the process, because a terminal does not change under a running
    program.
    """
    env = os.environ if environ is None else environ
    if not _decided:
        return apply_policy(None, environ=env, stream=stream)
    report = terminal_report(environ=env, stream=stream)
    return replace(report, ascii_mode=_ascii_mode, source='previous')


_reset_state()


class Glyphs:
    """Namespace facade over the module's single piece of state.

    The implementation is module-level functions (the switch is process state,
    not per-instance state, because there is one terminal); this class gives
    call sites a readable ``Glyphs.get('cursor')`` spelling without inventing an
    object to pass around.
    """

    register = staticmethod(register)
    register_many = staticmethod(register_many)
    probe = staticmethod(probe)
    reset = staticmethod(reset)
    get = staticmethod(get)
    unicode_of = staticmethod(unicode_of)
    is_ascii = staticmethod(is_ascii)
    set_ascii = staticmethod(set_ascii)
    probe_text = staticmethod(probe_text)
    transliterate = staticmethod(transliterate)
    terminal_report = staticmethod(terminal_report)
    apply_policy = staticmethod(apply_policy)
