import warnings

from console_window.backend import HeadlessBackend
from console_window.opts import ConsoleWindowOpts
from console_window.window import ConsoleWindow


def _make(head_rows=3, body_rows=5):
    return ConsoleWindow(
        opts=ConsoleWindowOpts(head_rows=head_rows, body_rows=body_rows),
        backend=HeadlessBackend(rows=24, cols=80),
    )


def _record(fn):
    # simplefilter('always') inside catch_warnings makes these assertions
    # independent of the suite-wide `filterwarnings = error::UserWarning`
    # setting in pyproject.toml.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        fn()
    return caught


def test_add_body_within_capacity_is_silent():
    win = _make(body_rows=5)
    try:
        caught = _record(lambda: [win.add_body(f'row {i}') for i in range(5)])
        assert [str(w.message) for w in caught] == []
        assert win.rows_dropped == 0
        assert win.body.row_cnt == 5
    finally:
        win.stop_curses()


def test_overflowing_the_body_pad_counts_rows_and_warns_once():
    win = _make(body_rows=5)
    try:
        caught = _record(lambda: [win.add_body(f'row {i}') for i in range(12)])
        assert len(caught) == 1
        assert caught[0].category is UserWarning
        assert 'body pad is full' in str(caught[0].message)
        # The excess is still discarded -- 7 of the 12 rows -- but no longer in
        # silence.
        assert win.rows_dropped == 7
        assert win.body.rows_dropped == 7
        assert win.head.rows_dropped == 0
        assert win.body.row_cnt == 5
        assert win.body.texts == [f'row {i}' for i in range(5)]
    finally:
        win.stop_curses()


def test_overflow_is_not_fatal_and_clear_rearms_the_warning():
    win = _make(body_rows=2)
    try:
        caught = _record(lambda: [win.add_body(f'a{i}') for i in range(9)])
        # No exception: the app limped along, exactly as it did before.
        assert len(caught) == 1
        assert win.rows_dropped == 7

        win.clear()
        assert win.rows_dropped == 0
        assert win.body.row_cnt == 0

        caught = _record(lambda: [win.add_body(f'b{i}') for i in range(3)])
        assert len(caught) == 1  # one per fill episode, not one per row
        assert win.rows_dropped == 1
    finally:
        win.stop_curses()


def test_head_pad_overflow_is_counted_and_summed():
    win = _make(head_rows=2, body_rows=2)
    try:
        def draw():
            for i in range(4):
                win.add_header(f'h{i}')
            for i in range(3):
                win.add_body(f'b{i}')

        caught = _record(draw)
        messages = [str(w.message) for w in caught]
        assert len(messages) == 2
        assert any('head pad is full' in m for m in messages)
        assert any('body pad is full' in m for m in messages)
        assert win.head.rows_dropped == 2
        assert win.body.rows_dropped == 1
        assert win.rows_dropped == 3
    finally:
        win.stop_curses()


def test_resume_on_a_full_pad_is_counted_too():
    win = _make(body_rows=1)
    try:
        win.add_body('only')
        caught = _record(lambda: win.add_body('more', resume=True))
        assert len(caught) == 1
        assert 'body pad is full' in str(caught[0].message)
        assert win.body.row_cnt == 1
        assert win.rows_dropped == 1
    finally:
        win.stop_curses()


def test_the_warning_blames_the_callers_line_not_the_library():
    win = _make(body_rows=1)
    try:
        caught = _record(lambda: [win.add_body('first'), win.add_body('second')])
        assert caught[0].filename.endswith('test_overflow.py')
    finally:
        win.stop_curses()
