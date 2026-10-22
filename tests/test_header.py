import curses

import pytest

from console_window import HeaderLine, Span
from console_window.backend import HeadlessBackend
from console_window.header import KEY, LABEL, PLAIN, SEARCH, parse_fancy_header
from console_window.opts import ConsoleWindowOpts
from console_window.widgets import IncrementalSearchBar
from console_window.window import ConsoleWindow

KEY_ATTR = curses.A_UNDERLINE | curses.A_BOLD  # 'Underline' mode key styling

# --- pure legacy scanner ----------------------------------------------------

def test_parse_bracket_key_strips_brackets():
    assert parse_fancy_header('[v]iew=compact') == [
        Span('v', KEY), Span('iew=compact', PLAIN)]


def test_parse_uppercase_key_word():
    assert parse_fancy_header('ESC:back') == [
        Span('ESC', KEY), Span(':', PLAIN), Span('back', PLAIN)]


def test_parse_leading_word_becomes_label():
    # Historical quirk: the first word is bolded whatever its case.
    assert parse_fancy_header('hello world') == [
        Span('hello', LABEL), Span(' world', PLAIN)]


def test_parse_search_pattern():
    assert parse_fancy_header('/filter me') == [
        Span('/filter', SEARCH), Span(' me', PLAIN)]


def test_parse_leaves_embedded_lowercase_key_unstyled():
    # Only UPPERCASE 'WORD:' tokens were matched by the legacy scanner.
    spans = parse_fancy_header('l:alert')
    assert spans == [Span('l:alert', PLAIN)]

# --- explicit builder -------------------------------------------------------

def test_builder_roles_and_plain_text():
    line = HeaderLine()
    line.text('a').key('v').bracket_key('b').label('Title').search('foo')
    assert line.spans == [
        Span('a', PLAIN),
        Span('v', KEY),
        Span('[', PLAIN), Span('b', KEY), Span(']', PLAIN),
        Span('Title', LABEL),
        Span('/foo', SEARCH),
    ]
    assert str(line) == 'av[b]Title/foo'


def test_builder_empty_and_len():
    assert len(HeaderLine()) == 0
    assert not HeaderLine()
    assert len(HeaderLine().text('x')) == 1


def test_builder_extend():
    a = HeaderLine().text('a')
    b = HeaderLine().key('b')
    a.extend(b)
    assert a.spans == [Span('a', PLAIN), Span('b', KEY)]


def test_builder_ignores_empty_text():
    assert HeaderLine().text('').key('').spans == []

# --- anti-misfire: structured text is never restyled ------------------------

def test_plain_text_that_looks_like_markup_is_not_restyled():
    # '/etc/passwd' and 'NOTE:' look like markup but are declared as plain text.
    line = HeaderLine().text('/etc/passwd NOTE:ok [v]')
    assert line.spans == [Span('/etc/passwd NOTE:ok [v]', PLAIN)]

# --- IncrementalSearchBar.as_header_line ------------------------------------

def test_search_bar_header_line_empty_when_idle():
    bar = IncrementalSearchBar()
    line = bar.as_header_line(prefix='/')
    assert len(line) == 0
    assert not line


def test_search_bar_header_line_search_span_when_inactive():
    bar = IncrementalSearchBar()
    bar.start('ab')
    bar.handle_key(10)  # ENTER -> accept, becomes inactive
    assert bar.as_header_line(prefix='/').spans == [Span('/ab', SEARCH)]


def test_search_bar_header_line_active_has_cursor_and_no_search_span():
    bar = IncrementalSearchBar()
    bar.start('ab')
    line = bar.as_header_line(prefix='/')
    assert '█' in str(line)
    assert all(span.role != SEARCH for span in line)


def test_get_display_string_keeps_prefix_spacer():
    # The legacy string API keeps its spacer (pinned by test_widgets); the token
    # path (as_header_line) is the one that has no such need.
    bar = IncrementalSearchBar()
    bar.start('ab')
    disp = bar.get_display_string(prefix='/')
    assert disp.startswith('/ ')
    assert '█' in disp

# --- headless render --------------------------------------------------------

def _make_window():
    return ConsoleWindow(
        opts=ConsoleWindowOpts(head_rows=3, body_rows=5),
        backend=HeadlessBackend(rows=24, cols=80),
        singleton=False,
    )


def test_add_header_line_renders_explicit_spans():
    win = _make_window()
    try:
        win.add_header_line(HeaderLine().label('T').text(' ').bracket_key('v'),
                            mode='Underline')
        assert win.head.texts[0] == 'T [v]'
        attrs = [attr for attr, _count in win.head.text_attrs[0]]
        assert curses.A_BOLD in attrs          # the LABEL run
        assert KEY_ATTR in attrs               # the KEY run
    finally:
        win.stop_curses()


def test_add_header_line_never_highlights_plain_data():
    win = _make_window()
    try:
        win.add_header_line(HeaderLine().text('/etc/passwd'), mode='Underline')
        assert win.head.texts[0] == '/etc/passwd'
        # No SEARCH (bold+reverse) run: the data was not misread as a pattern.
        search_attr = curses.A_BOLD | curses.A_REVERSE
        assert all(attr != search_attr for attr, _count in win.head.text_attrs[0])
    finally:
        win.stop_curses()


def test_add_fancy_header_string_form_still_parses():
    win = _make_window()
    try:
        win.add_fancy_header('[v]iew', mode='Underline')
        assert win.head.texts[0] == 'view'
        attrs = [attr for attr, _count in win.head.text_attrs[0]]
        assert KEY_ATTR in attrs
    finally:
        win.stop_curses()


def test_add_fancy_header_off_adds_raw_line():
    win = _make_window()
    try:
        win.add_fancy_header('[v]iew', mode='Off')
        assert win.head.texts[0] == '[v]iew'  # no markup processing
    finally:
        win.stop_curses()


def test_add_fancy_header_headerline_strips_bracket_delimiters():
    win = _make_window()
    try:
        win.add_fancy_header(
            HeaderLine().text(' ').bracket_key('v').text('iew=compact'),
            mode='Underline',
        )
        assert win.head.texts[0] == ' view=compact'
        attrs = [attr for attr, _count in win.head.text_attrs[0]]
        assert KEY_ATTR in attrs
    finally:
        win.stop_curses()


def test_add_fancy_header_headerline_off_keeps_bracket_delimiters():
    win = _make_window()
    try:
        win.add_fancy_header(
            HeaderLine().text(' ').bracket_key('v').text('iew=compact'),
            mode='Off',
        )
        assert win.head.texts[0] == ' [v]iew=compact'
    finally:
        win.stop_curses()


def test_add_fancy_header_headerline_preserves_explicit_roles():
    # The fancy path only elides bracket delimiters around KEY spans; it does
    # not re-guess roles from the rendered text (lowercase '?:' stays a key).
    win = _make_window()
    try:
        win.add_fancy_header(
            HeaderLine().text(' ').key('?').text(':help'),
            mode='Underline',
        )
        assert win.head.texts[0] == ' ?:help'
        attrs = [attr for attr, _count in win.head.text_attrs[0]]
        assert KEY_ATTR in attrs
    finally:
        win.stop_curses()


def test_string_reparse_drops_keys_the_legacy_grammar_cannot_spell():
    # str(line) is pure text, so the legacy scanner's two KEY rules ('[x]' and
    # 'UPPERCASE:') are all that survive a round trip.  'l:' and '?:' match
    # neither, which is why the sample spells those keys as '[l]'/'[?]'.
    win = _make_window()
    try:
        win.add_fancy_header(' l:alrtDemo ?:help', mode='Underline')
        assert win.head.texts[0] == ' l:alrtDemo ?:help'
        attrs = [attr for attr, _count in win.head.text_attrs[0]]
        assert KEY_ATTR not in attrs
    finally:
        win.stop_curses()


def _expand_cells(attrs):
    return [attr for attr, count in attrs for _ in range(count)]


def test_token_and_string_paths_converge_for_legacy_spelled_keys():
    # A HeaderLine whose KEY spans are spelled the way the string grammar reads
    # them back renders cell-for-cell identically whether it is handed over as
    # tokens or as str(line) re-parsed by the legacy scanner.
    line = (HeaderLine()
            .text('  ').bracket_key('v').text('iew=full')
            .text(' ').bracket_key('?').text(':help')
            .text(' ').key('SPC').text(':process'))
    as_tokens = _make_window()
    as_string = _make_window()
    try:
        as_tokens.add_fancy_header(line, mode='Underline')
        as_string.add_fancy_header(str(line), mode='Underline')
        assert as_string.head.texts[0] == as_tokens.head.texts[0]
        # Runs may differ in grouping ('iew=full ' vs 'iew=full' + ' '), so
        # compare the per-cell attributes, which is what the pad paints.
        assert (_expand_cells(as_string.head.text_attrs[0])
                == _expand_cells(as_tokens.head.text_attrs[0]))
    finally:
        as_tokens.stop_curses()
        as_string.stop_curses()


@pytest.mark.parametrize('role', [KEY, LABEL, SEARCH, PLAIN])


def test_resolve_header_attr_off_is_plain(role):
    assert ConsoleWindow._resolve_header_attr(role, 'Off', None) is None
