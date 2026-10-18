import curses
import logging

import pytest

import console_window.signals as signals
import console_window.window as window_mod
from console_window.backend import HeadlessBackend
from console_window.context import Context
from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow, TerminalTooSmallError

# ``curses.ACS_*`` are only bound once curses has been initialised (i.e. after
# initscr()).  Stand-ins let the drawing helpers run against HeadlessBackend.
_ACS_STANDINS = {
    'ACS_HLINE': '-',
    'ACS_VLINE': '|',
    'ACS_ULCORNER': '+',
    'ACS_URCORNER': '+',
    'ACS_LLCORNER': '+',
    'ACS_LRCORNER': '+',
}


@pytest.fixture(autouse=True)
def _headless_curses(monkeypatch):
    # The only curses names the drawing helpers still need are the ACS_* box
    # glyphs, which are unbound until initscr().  The process-global calls
    # (doupdate/curs_set/update_lines_cols/is_term_resized) now go through
    # HeadlessBackend, so they need no monkeypatching here (AUDIT.md §3.3).
    for name, value in _ACS_STANDINS.items():
        if not hasattr(window_mod.curses, name):
            monkeypatch.setattr(window_mod.curses, name, value, raising=False)


@pytest.fixture
def make():
    # Factory that tracks every window it builds so teardown is unconditional.
    created = []

    def _make(backend=None, **opts):
        backend = backend if backend is not None else HeadlessBackend(rows=24, cols=80)
        win = ConsoleWindow(opts=ConsoleWindowOpts(**opts), backend=backend)
        created.append(win)
        return win, backend

    yield _make
    for win in created:
        if win.scr is not None:
            win.stop_curses()


# --- prompt(): the basic contract ------------------------------------------

def test_prompt_returns_a_handled_key(make):
    win, backend = make(keys={ord('q')}, relax_handled_keys=False)
    backend.queue_keys(ord('q'))
    assert win.prompt(seconds=0.5) == ord('q')


def test_prompt_returns_a_key_queued_in_pending_keys(make):
    # The lock-free hand-off queue: a key parked during flash() must be the next
    # thing prompt() returns, and must be consumed in the process.
    win, _backend = make(keys={ord('z')})
    win.pending_keys.add(ord('z'))
    assert win.prompt(seconds=0.5) == ord('z')
    assert win.pending_keys == set()


def test_prompt_ignores_unknown_keys_then_times_out(make):
    win, backend = make(relax_handled_keys=False)
    backend.queue_keys(ord('x'))  # not handled, not navigation
    assert win.prompt(seconds=0.02) is None


def test_prompt_relax_handled_keys_passes_unknown_key_to_app(make):
    win, backend = make(relax_handled_keys=True)
    backend.queue_keys(ord('~'))
    assert win.prompt(seconds=0.5) == ord('~')


def test_prompt_passthrough_mode_returns_printable_keys(make):
    win, backend = make()
    win.passthrough_mode = True
    backend.queue_keys(ord('p'))
    assert win.prompt(seconds=0.5) == ord('p')


def test_prompt_passthrough_records_demo_indicator(make):
    win, backend = make(demo_mode=True)
    win.passthrough_mode = True
    backend.queue_keys(ord('p'))
    assert win.prompt(seconds=0.5) == ord('p')
    assert win.last_demo_key == ' p '


# --- prompt(): Ctrl-C as an application key --------------------------------

def test_prompt_returns_etx_when_ctrl_c_is_handled(monkeypatch, make):
    win, _backend = make(ctrl_c_terminates=False, keys={0x3})
    monkeypatch.setattr(signals, 'ctrl_c_flag', True)
    assert win.prompt(seconds=0.5) == 0x3
    assert signals.ctrl_c_flag is False


def test_prompt_requeues_a_handled_key_seen_during_ctrl_c(monkeypatch, make):
    win, backend = make(ctrl_c_terminates=False, keys={ord('q')})
    monkeypatch.setattr(signals, 'ctrl_c_flag', True)
    backend.queue_keys(ord('q'))
    # The key is preserved for the app rather than swallowed by the Ctrl-C path.
    assert win.prompt(seconds=0.5) == ord('q')
    assert win.pending_keys == set()


# --- prompt(): navigation ---------------------------------------------------

def test_j_and_k_move_the_pick_one_row(make):
    win, backend = make(pick_mode=True, body_rows=10, head_rows=2)
    for i in range(5):
        win.add_body(f'row {i}')
    win.fix_positions()
    assert win.pick_pos == 0

    backend.queue_keys(ord('j'))
    assert win.prompt() is None  # return_if_pos_change defaults True
    assert win.pick_pos == 1

    backend.queue_keys(ord('k'))
    win.prompt()
    assert win.pick_pos == 0


def test_navigation_scrolls_the_body_without_pick_mode(make):
    win, backend = make(backend=HeadlessBackend(rows=10, cols=80), body_rows=50, head_rows=2)
    for i in range(10):
        win.add_body(f'row {i}')
    win.fix_positions()
    backend.queue_keys(ord('j'))
    win.prompt()
    assert win.scroll_pos == 1


def test_navigation_key_clears_the_demo_indicator(make):
    win, backend = make(demo_mode=True, body_rows=10, head_rows=2)
    for i in range(5):
        win.add_body(f'r{i}')
    win.last_demo_key = ' x '
    backend.queue_keys(ord('j'))
    win.prompt()
    assert win.last_demo_key == ''


def test_prompt_navigation_key_families_all_drive_the_engine(make):
    # One pass over every navigation branch in prompt(); the point is that each
    # key is consumed and the scroll position stays inside its legal range.
    win, backend = make(backend=HeadlessBackend(rows=12, cols=80), body_rows=60, head_rows=2)
    for i in range(40):
        win.add_body(f'row {i}')
    win.fix_positions()

    keys = [
        ord('j'), ord('k'), curses.KEY_DOWN, curses.KEY_UP,
        2, curses.KEY_PPAGE, 21, 6, curses.KEY_NPAGE, 4,
        ord('0'), curses.KEY_HOME, ord('$'), curses.KEY_END,
        ord('H'), ord('M'), ord('L'),
    ]
    for key in keys:
        win.scroll_pos = min(10, win.max_scroll_pos)
        win.fix_positions()
        backend.queue_keys(key)
        win.prompt()

    assert 0 <= win.scroll_pos <= win.max_scroll_pos


def test_prompt_renders_after_navigation_when_return_if_pos_change_is_false(make):
    win, backend = make(return_if_pos_change=False, body_rows=10, head_rows=2)
    for i in range(5):
        win.add_body(f'r{i}')
    backend.queue_keys(ord('j'))
    assert win.prompt() is None
    # render() ran, so the pads were pushed to the screen.
    assert win.body.pad.calls_named('noutrefresh')


# --- prompt(): reaching non-pickable DECOR rows at either end ---------------

def _add_decor_body(win, pickable=20, decor=200):
    for i in range(pickable):
        win.add_body(f'item {i}', context=Context(genre='item'))
    for i in range(decor):
        win.add_body(f'filler {i}', context=Context(genre='DECOR'))


def test_trailing_decor_is_reachable_by_scrolling_down(make):
    # 20 pickable rows followed by 200 DECOR: pressing j past the last pickable
    # row must scroll into the filler instead of snapping back to the pick.
    win, backend = make(backend=HeadlessBackend(rows=24, cols=80),
                        pick_mode=True, body_rows=400, head_rows=2)
    _add_decor_body(win)
    win.fix_positions()

    for _ in range(500):
        backend.queue_keys(ord('j'))
        win.prompt()

    assert win.pick_pos == 19             # pick stayed on the last pickable row
    assert win.scroll_pos == win.max_scroll_pos > 0
    assert win.free_scroll is True


def test_a_real_pick_move_resynchronises_the_view(make):
    win, backend = make(backend=HeadlessBackend(rows=24, cols=80),
                        pick_mode=True, body_rows=400, head_rows=2)
    _add_decor_body(win)
    win.fix_positions()
    for _ in range(500):
        backend.queue_keys(ord('j'))
        win.prompt()
    assert win.free_scroll is True

    backend.queue_keys(ord('k'))
    win.prompt()
    assert win.pick_pos == 18
    assert win.scroll_pos == 18
    assert win.free_scroll is False


def test_page_and_end_reach_trailing_decor(make):
    win, backend = make(backend=HeadlessBackend(rows=24, cols=80),
                        pick_mode=True, body_rows=400, head_rows=2)
    _add_decor_body(win)
    win.fix_positions()

    backend.queue_keys(6)  # Ctrl-f = page down
    win.prompt()
    assert win.scroll_pos == win.scroll_view_size

    backend.queue_keys(ord('$'))  # END
    win.prompt()
    assert win.scroll_pos == win.max_scroll_pos


def test_scroll_indicator_follows_the_viewport_while_free_scrolling(make):
    win, backend = make(backend=HeadlessBackend(rows=24, cols=80),
                        pick_mode=True, body_rows=400, head_rows=2)
    _add_decor_body(win)
    win.fix_positions()
    start = win._scroll_indicator_col()

    for _ in range(500):
        backend.queue_keys(ord('j'))
        win.prompt()

    assert win.free_scroll is True
    assert win._scroll_indicator_col() > start


def test_leading_decor_is_reachable_by_scrolling_up(make):
    win, backend = make(backend=HeadlessBackend(rows=24, cols=80),
                        pick_mode=True, body_rows=400, head_rows=2)
    for i in range(200):
        win.add_body(f'filler {i}', context=Context(genre='DECOR'))
    for i in range(20):
        win.add_body(f'item {i}', context=Context(genre='item'))
    win.fix_positions()
    # The pick starts on the first pickable row; scrolling up reveals the DECOR
    # rows above it (which the old clamp already allowed), and scrolling back
    # down re-synchronises.
    start_pick = win.pick_pos
    backend.queue_keys(ord('k'))
    win.prompt()
    assert win.pick_pos == start_pick
    assert win.free_scroll is True


# --- prompt(): resize and minimum-size handling -----------------------------

def test_prompt_resize_resets_dimensions_and_returns(make):
    win, backend = make()
    backend.queue_keys(curses.KEY_RESIZE)
    # KEY_RESIZE re-reads the size, _check_min_size passes at 24x80, so prompt
    # breaks out of its loop and returns None.
    assert win.prompt(seconds=0.5) is None
    assert (win.rows, win.cols) == (24, 80)


def test_prompt_min_size_abort_returns_esc_when_handled(make):
    win, backend = make(HeadlessBackend(rows=5, cols=5), keys={27}, relax_handled_keys=False)
    backend.queue_keys(curses.KEY_RESIZE, 27)  # KEY_RESIZE then ESC in _check_min_size
    assert win.prompt(seconds=0.5) == 27


# --- render() / render_once(): the drawing half -----------------------------

def test_render_draws_gutter_separator_and_indicator(make):
    win, backend = make(pick_mode=True, body_rows=10, head_rows=2, pick_size=2)
    win.add_header('HDR')
    for i in range(5):
        win.add_body(f'body {i}')
    win.pick_mode = True
    win.pick_pos = 2
    win._pick_clear_pending = True  # force the "clear every row" path

    win.render(redraw=True)

    assert backend.screen.calls_named('vline')  # pick gutter
    assert backend.screen.calls_named('hline')  # header separator
    assert win.body.pad.calls_named('noutrefresh')
    assert win.head.pad.calls_named('noutrefresh')
    assert win.last_pick_pos == 2


def test_scroll_indicator_span_single_cell_branch(make):
    win, _backend = make(single_cell_scroll_indicator=True)
    assert win._scroll_indicator_span(10) == (10, 1)


def test_scroll_indicator_span_proportional_branch(make):
    win, _backend = make(single_cell_scroll_indicator=False)
    win.scroll_view_size = 20
    win.body.row_cnt = 40
    win.cols = 80
    bot, cnt = win._scroll_indicator_span(40)
    assert bot >= 1
    assert cnt >= 1


def test_render_retries_transient_curses_errors(monkeypatch, make):
    win, _backend = make()
    calls = {'n': 0}
    real = win.render_once

    def flaky(redraw=False):
        calls['n'] += 1
        if calls['n'] == 1:
            raise window_mod.curses.error('transient')
        return real(redraw)

    monkeypatch.setattr(win, 'render_once', flaky)
    monkeypatch.setattr(window_mod.time, 'sleep', lambda s: None)
    win.render()
    assert calls['n'] == 2


def test_render_gives_up_after_the_retry_budget(monkeypatch, caplog, make):
    win, backend = make()
    monkeypatch.setattr(ConsoleWindow, 'render_retry_seconds', 0.01)
    monkeypatch.setattr(window_mod.time, 'sleep', lambda s: None)

    def boom(redraw=False):
        raise window_mod.curses.error('persistent')

    monkeypatch.setattr(win, 'render_once', boom)
    with caplog.at_level(logging.ERROR, logger='console_window.window'):
        with pytest.raises(window_mod.curses.error):
            win.render()
    assert backend.stopped is True
    assert 'curses error while rendering' in caplog.text
    assert 'pick_mode=False' in caplog.text


# --- draw(): the direct row writer ------------------------------------------

def test_draw_writes_a_row_and_tracks_row_cnt(make):
    win, _backend = make(body_rows=10, body_cols=40)
    win.draw(2, 1, 'hello')
    assert win.body.row_cnt == 3
    assert win.body.texts[2] == ' hello'
    assert win.body.pad.calls_named('addstr')


def test_draw_out_of_bounds_is_a_no_op(make):
    win, _backend = make(body_rows=10, body_cols=40)
    for y, x in ((-1, 0), (0, -1), (999, 0), (0, 999)):
        win.draw(y, x, 'x')
    assert win.body.row_cnt == 0
    assert win.body.texts == []


def test_draw_header_flag_targets_the_head_pad(make):
    win, _backend = make(head_rows=5)
    win.draw(0, 0, 'HDR', header=True)
    assert win.head.row_cnt == 1
    assert win.head.pad.calls_named('addstr')


def test_draw_width_and_leftpad_use_display_cells(make):
    win, _backend = make(body_rows=10, body_cols=40)
    win.draw(0, 0, 'ab', width=5, leftpad=True)
    assert win.body.texts[0] == '   ab'


def test_draw_handles_wide_characters(make):
    win, _backend = make(body_rows=10, body_cols=40)
    win.draw(0, 0, '漢字')
    assert win.body.texts[0] == '漢字'


# --- highlight_picked() and the attribute run painter -----------------------

def test_highlight_picked_clears_and_repaints_with_pick_size(make):
    win, _backend = make(pick_mode=True, pick_size=2, body_rows=10)
    for i in range(6):
        win.add_body(f'row {i}')
    win.pick_mode = True
    win.pick_size = 2
    win.pick_pos = 2
    win._pick_clear_pending = True
    win.highlight_picked()
    assert win.body.pad.calls_named('addstr')
    assert win.last_pick_pos == 2
    assert win._pick_clear_pending is False


def test_pick_range_repaints_when_position_is_unchanged(make):
    # set_pick_range() must repaint the picked row even when it did not move:
    # the full clear removes the old highlight, so treating "same position" as
    # "nothing to do" would leave the row unhighlighted.
    win, _backend = make(pick_mode=True, pick_size=1, body_rows=10)
    win.add_body('row 0')
    win.add_body('row 1')
    win.pick_pos = 1
    win.last_pick_pos = 1
    win.set_pick_range(0, 2)
    assert win._pick_clear_pending is True
    win.highlight_picked()
    assert win._pick_clear_pending is False
    picked = [args for _name, args, _kw in win.body.pad.calls_named('addstr')
              if args[0] == 1]
    assert picked
    assert any(args[3] & curses.A_REVERSE for args in picked)


def test_set_pick_mode_requests_a_full_clear(make):
    win, _backend = make()
    win.set_pick_mode(True, 2)
    assert win._pick_clear_pending is True


def test_draw_picked_rows_plain_line_with_range(make):
    win, _backend = make(pick_mode=True, pick_range=[0, 2], body_rows=10)
    for i in range(3):
        win.add_body(f'ab{i}')
    win.pick_mode = True
    win.body.text_attrs = []  # force the no-run-length "plain line" painter
    win._draw_picked_rows([0])
    assert win.body.pad.calls_named('addstr')


def test_draw_picked_rows_plain_line_without_range(make):
    win, _backend = make(pick_mode=True, pick_range=None, body_rows=10)
    for i in range(3):
        win.add_body(f'ab{i}')
    win.pick_mode = True
    win.body.text_attrs = []
    win._draw_picked_rows([0])
    assert win.body.pad.calls_named('addstr')


def test_draw_picked_rows_applies_mod_pick(make):
    win, _backend = make(pick_mode=True, mod_pick=str.upper, body_rows=10)
    for i in range(3):
        win.add_body(f'ab{i}')
    win.pick_mode = True
    win._draw_picked_rows([0])
    assert win.body.pad.calls_named('addstr')


def test_draw_attr_runs_split_around_the_pick_range(make):
    win, _backend = make(pick_mode=True, pick_range=[3, 6], body_rows=10)
    win.add_body('abcdefghij')  # one run-length-coded row
    win.pick_mode = True
    win._draw_picked_rows([0])
    assert win.body.pad.calls_named('addstr')


# --- answer(): the dialog ---------------------------------------------------

def test_answer_submits_the_typed_string(make):
    win, backend = make()
    backend.queue_keys(ord('h'), ord('i'), 10)
    assert win.answer() == 'hi'


def test_answer_esc_aborts_and_returns_none(make):
    win, backend = make()
    backend.queue_keys(27)
    assert win.answer() is None


def test_answer_dialog_abort_none_ignores_esc(make):
    win, backend = make(dialog_abort=None)
    backend.queue_keys(27, 10)  # ESC ignored, ENTER submits
    assert win.answer(seed='ab') == 'ab'


def test_answer_esc_esc_requires_two_presses(make):
    # A single ESC only arms the abort; the dialog keeps reading, so a second
    # key (ENTER) is required to finish and the text survives.
    win, backend = make(dialog_abort='ESC-ESC')
    backend.queue_keys(27, 10)
    assert win.answer(seed='ab') == 'ab'
    # Two ESCs inside the window abort and discard the edit.
    win2, backend2 = make(dialog_abort='ESC-ESC')
    backend2.queue_keys(27, 27)
    assert win2.answer() is None


def test_answer_edits_with_moves_and_backspace(make):
    win, backend = make()
    backend.queue_keys(ord('h'), ord('i'), curses.KEY_LEFT, curses.KEY_BACKSPACE, 10)
    assert win.answer() == 'i'


def test_answer_deletes_forward_with_key_dc(make):
    win, backend = make()
    backend.queue_keys(curses.KEY_HOME, curses.KEY_DC, 10)
    assert win.answer(seed='ab') == 'b'


def test_answer_moves_the_cursor_between_wrapped_lines(make):
    win, backend = make()
    seed = 'abcdefghijklmnopqrstuvwxyz'
    backend.queue_keys(curses.KEY_UP, 10)
    assert win.answer(seed=seed, width=10) == seed


def test_answer_debug_indicator_path(make):
    win, backend = make(answer_show_redraws=True)
    backend.queue_keys(10)
    assert win.answer() == ''


def test_answer_handles_resize_then_submits(make):
    win, backend = make()
    backend.queue_keys(curses.KEY_RESIZE, 10)
    assert win.answer(seed='hi') == 'hi'


def test_answer_raises_when_terminal_too_small(make):
    win, _backend = make(HeadlessBackend(rows=5, cols=10))
    with pytest.raises(TerminalTooSmallError) as excinfo:
        win.answer()
    assert (excinfo.value.required_cols, excinfo.value.required_rows) == (70, 20)
    assert (excinfo.value.actual_cols, excinfo.value.actual_rows) == (10, 5)


# --- alert(): the scrollable message box ------------------------------------

def _tall_message(lines=50, width=60):
    # wrap() splits on whitespace, so each `width`-cell word takes its own line
    # in the 76-cell content column (60 + 1 + 60 > 76): `lines` wrapped rows.
    return ' '.join(['y' * width] * lines)


def _drawn_chars(backend):
    return [c[1][2] for c in backend.screen.calls_named('addch') if len(c[1]) >= 3]


def test_alert_runs_headless_and_acknowledges(make):
    win, backend = make()
    backend.queue_keys(10)  # ENTER
    win.alert(message='hello', title='T')  # must not raise or block


def test_alert_scrolls_tall_message_one_row_per_j(make):
    win, backend = make()
    backend.queue_keys(ord('j'), ord('j'), 10)
    win.alert(message=_tall_message())
    pad = backend.pads[-1]  # the alert content pad (head/body are pads 0/1)
    assert pad.calls_named('refresh')[-1][1][0] == 2


def test_alert_page_down_scrolls_a_full_visible_page(make):
    win, backend = make()
    backend.queue_keys(curses.KEY_NPAGE, 10)
    win.alert(message=_tall_message())
    pad = backend.pads[-1]
    assert pad.calls_named('refresh')[-1][1][0] == 20  # box_height - 2 borders


def test_alert_end_jumps_to_the_bottom(make):
    win, backend = make()
    backend.queue_keys(curses.KEY_END, 10)
    win.alert(message=_tall_message())
    pad = backend.pads[-1]
    assert pad.calls_named('refresh')[-1][1][0] == 30  # 50 rows - 20 visible


def test_alert_draws_more_and_up_markers_while_scrolling(make):
    win, backend = make()
    backend.queue_keys(ord('j'), 10)
    win.alert(message=_tall_message())
    drawn = _drawn_chars(backend)
    assert '▼' in drawn  # content continues below the fold
    assert '▲' in drawn  # one row scrolled above the fold


def test_alert_short_message_does_not_scroll(make):
    win, backend = make()
    backend.queue_keys(10)
    win.alert(message='hello')
    pad = backend.pads[-1]
    assert pad.calls_named('refresh')[-1][1][0] == 0
    drawn = _drawn_chars(backend)
    assert '▼' not in drawn and '▲' not in drawn


def test_alert_height_cap_makes_a_short_message_scrollable(make):
    win, backend = make()
    backend.queue_keys(ord('j'), 10)
    win.alert(message=_tall_message(lines=10), _height=3)  # 3 visible rows
    pad = backend.pads[-1]
    assert pad.calls_named('refresh')[-1][1][0] == 1


def test_alert_non_scroll_key_is_ignored(make):
    win, backend = make()
    backend.queue_keys(ord('x'), 10)  # 'x' is not a scroll command
    win.alert(message=_tall_message())
    pad = backend.pads[-1]
    assert pad.calls_named('refresh')[-1][1][0] == 0


def test_alert_redraws_after_resize_then_acknowledges(make):
    win, backend = make()
    before = len(backend.pads)
    backend.queue_keys(curses.KEY_RESIZE, 10)
    win.alert(message='hello')
    # The initial draw plus one rebuild of the pad after the resize event.
    assert len(backend.pads) == before + 2


def test_alert_returns_without_blocking_when_terminal_too_small(make):
    win, _backend = make(HeadlessBackend(rows=4, cols=10))
    win.alert(message='hi')  # no keys queued: must return on the size check
    assert win._scr_timeout_ms == ConsoleWindow.timeout_ms  # timeout restored


# --- resize recovery --------------------------------------------------------

def test_recover_from_resize_drains_pending_keys(make):
    win, backend = make()
    backend.queue_keys(ord('a'), curses.KEY_RESIZE, ord('b'))
    win._recover_from_resize()
    assert backend.screen.keys == []
    names = [c[0] for c in backend.screen.calls]
    assert 'nodelay' in names
    assert win.scr.getch() == -1  # the queue really is empty


def test_show_too_small_dialog_returns_true_on_esc(make):
    win, backend = make()
    backend.queue_keys(27)
    assert win._show_too_small_dialog(5) is True


def test_show_too_small_dialog_keeps_waiting_on_resize(make):
    win, backend = make()
    backend.queue_keys(curses.KEY_RESIZE)
    assert win._show_too_small_dialog(5) is False
