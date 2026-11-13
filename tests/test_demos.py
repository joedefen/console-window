"""Headless smoke tests and manifest checks for the demo family.

Every ``demos/demo-*.py`` is imported, built against a HeadlessBackend, drawn
once, then run through its own ``main_loop()`` with ``q`` queued.  The manifest
tests keep "one feature, one demo" true: each key names a real demo, every demo
owns at least one key, each file's ``Owns:`` docstring agrees with the map, and
the appendix in ``docs/DEMO-APPS.md`` is the rendered table.
"""

from __future__ import annotations

import curses
import importlib.util
import pathlib
import sys

import pytest

from console_window import Appearance, Theme
from console_window.backend import HeadlessBackend

DEMOS = pathlib.Path(__file__).resolve().parents[1] / 'demos'
if str(DEMOS) not in sys.path:
    sys.path.insert(0, str(DEMOS))

import features  # noqa: E402  (demos/ must be on sys.path first)

_MODULES: dict[str, object] = {}

# curses.ACS_* are unbound until initscr(); the headless drawing code needs them.
_ACS_STANDINS = {
    'ACS_HLINE': '-',
    'ACS_VLINE': '|',
    'ACS_ULCORNER': '+',
    'ACS_URCORNER': '+',
    'ACS_LLCORNER': '+',
    'ACS_LRCORNER': '+',
}


def _demo_paths() -> list[pathlib.Path]:
    return sorted(DEMOS.glob('demo-*.py'))


def _demo_name(path: pathlib.Path) -> str:
    return path.stem[len('demo-'):]


def _load(path: pathlib.Path):
    module = _MODULES.get(path.stem)
    if module is None:
        module_name = 'demo_under_test_' + path.stem.replace('-', '_')
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        _MODULES[path.stem] = module
    return module


def _load_named(name: str):
    return _load(DEMOS / f'demo-{name}.py')


def _app(name: str, rows: int = 40, cols: int = 120):
    module = _load_named(name)
    backend = HeadlessBackend(rows=rows, cols=cols)
    app = module.build_app(backend=backend, singleton=False)
    return module, app, backend


@pytest.fixture(autouse=True)
def _headless_curses_stubs(monkeypatch):
    # curses.has_colors()/color_pair() raise until initscr() has succeeded, and
    # the drawing code (including the theme picker) calls both.
    monkeypatch.setattr(curses, 'has_colors', lambda: False, raising=False)
    monkeypatch.setattr(curses, 'color_pair', lambda n=0: n << 8, raising=False)
    for name, value in _ACS_STANDINS.items():
        if not hasattr(curses, name):
            monkeypatch.setattr(curses, name, value, raising=False)


@pytest.fixture(autouse=True)
def _appearance_state(monkeypatch):
    monkeypatch.setattr(Appearance, '_COLORS_ENABLED', True)
    monkeypatch.setattr(Theme, '_current', None)


# --- every demo builds, draws and quits ------------------------------------

@pytest.mark.parametrize('path', _demo_paths(), ids=_demo_name)
def test_every_demo_builds_draws_and_quits(path):
    module = _load(path)
    backend = HeadlessBackend(rows=40, cols=120)

    app = module.build_app(backend=backend, singleton=False)
    app.draw_once()

    assert app.win.head.row_cnt > 0
    assert app.win.body.row_cnt > 0

    backend.queue_keys(ord('q'))
    app.main_loop()

    assert app.running is False
    assert backend.stopped is True


# --- manifest --------------------------------------------------------------

def test_demo_order_matches_the_files_on_disk():
    assert set(features.DEMO_ORDER) == {_demo_name(path) for path in _demo_paths()}


def test_every_feature_names_an_existing_demo():
    demos = {_demo_name(path) for path in _demo_paths()}
    assert set(features.FEATURES.values()) <= demos


def test_every_demo_owns_at_least_one_feature():
    demos = {_demo_name(path) for path in _demo_paths()}
    for demo in demos:
        assert features.owned_by(demo), demo


def test_no_feature_key_has_two_owners():
    # A dict cannot hold a duplicate key; this guards the shape as the map is
    # edited (for example by a generated update).
    assert len(features.FEATURES) == len(set(features.FEATURES))


def _declared_owns(text: str) -> set[str] | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith('Owns:'):
            continue
        parts = [line.split('Owns:', 1)[1]]
        for following in lines[index + 1:]:
            if following.startswith(' ') and not following.strip().startswith('"""'):
                parts.append(following.strip())
            else:
                break
        return {part.strip() for part in ','.join(parts).split(',') if part.strip()}
    return None


@pytest.mark.parametrize('path', _demo_paths(), ids=_demo_name)
def test_each_demo_docstring_matches_its_features(path):
    demo = _demo_name(path)
    declared = _declared_owns(path.read_text(encoding='utf-8'))
    assert declared is not None, f'{path} has no "Owns:" docstring line'
    assert declared == set(features.owned_by(demo)), demo


def test_the_appendix_is_the_rendered_manifest():
    document = (DEMOS.parent / 'docs' / 'DEMO-APPS.md').read_text(encoding='utf-8')
    appendix = document.split('## Appendix: feature key \u2192 demo', 1)[1]
    start = appendix.index('| Feature key')
    assert appendix[start:].strip() == features.render_table()


# --- feature-specific checks, ported from the old sample-app tests ----------

def test_c_options_scopes_order_to_main_and_binds_every_action():
    module, app, _backend = _app('c-options')
    try:
        assert app.spin.key_scopes[(ord('o'), module.MAIN_ST)].attr == 'order'
        assert (ord('o'), module.HELP_ST) not in app.spin.key_scopes
        for option in app.spin.options:
            if option.genre != 'action':
                continue
            assert any(hasattr(screen, f'{option.attr}_ACTION')
                       for screen in app.stack.screen_objects.values()), option.attr
    finally:
        app.win.stop_curses()


def test_e_search_filters_on_accept_and_clears_with_escape():
    _module, app, _backend = _app('e-search')
    try:
        app.draw_once()

        app.handle_key(ord('/'))
        app.stack.perform_actions(app.spin)
        assert app.filter_bar.is_active is True
        assert app.win.passthrough_mode is True

        for key in (ord('1'), ord('0'), 10):
            app.handle_key(key)
        assert app.filter_text == '10'
        assert app.filter_bar.is_active is False
        assert app.win.passthrough_mode is False

        app.handle_key(27)  # the screen-local ESC subtracts MAIN from escape
        app.stack.perform_actions(app.spin)
        assert app.filter_text == ''
    finally:
        app.win.stop_curses()


def test_b_stack_pushes_and_pops_and_keeps_both_screens():
    _module, app, _backend = _app('b-stack')
    try:
        app.draw_once()
        app.handle_key(ord('2'))
        assert app.stack.curr.name == 'TWO'
        app.draw_once()
        app.handle_key(27)
        assert app.stack.curr.name == 'ONE'
    finally:
        app.win.stop_curses()


def test_f_prompts_draw_under_the_row_and_run_callbacks():
    _module, app, _backend = _app('f-prompts')
    try:
        app.draw_once()
        app.win.pick_pos = 0
        rank = app.win.get_picked_context().item['rank']

        app.main.confirm_ACTION()
        assert app.win.prompt_active is True
        assert app.prompt_rank == rank

        app.main.clear()
        app.main.draw_screen()
        assert any('Process rank' in text and '[Press "y" or ESC]' in text
                   for text in app.win.body.texts)
        assert any(text.strip() == 'Marks the row as processed'
                   for text in app.win.body.texts)

        app.handle_key(ord('y'))
        assert app.win.prompt_active is False
        assert app.prompt_rank is None
        assert rank in app.processed
        assert app.win.current_status[0] == f'Processed rank {rank}'
    finally:
        app.win.stop_curses()


def test_j_themes_apply_mono_and_name_it_in_the_picker():
    _module, app, _backend = _app('j-themes')
    try:
        assert app.opts.theme == app.win.theme == 'default'

        app.apply_theme_choice(Theme.MONO)
        assert Theme.MONO == app.opts.theme == app.win.theme
        assert Appearance.colors_enabled() is False

        app.stack.push(app.themes, 0)
        app.draw_once()
        assert 'mono' in app.win.head.texts[0]
        assert all('Color:' not in row for row in app.win.head.texts)
    finally:
        app.win.stop_curses()


def test_j_themes_picker_cycle_remembers_the_choice():
    module = _load_named('j-themes')
    store = module.DemoThemeStore()
    backend = HeadlessBackend(rows=40, cols=120)
    app = module.build_app(backend=backend, singleton=False, store=store)
    try:
        app.stack.push(app.themes, 0)
        app.handle_key(ord('t'))
        app.stack.perform_actions(app.spin)
        assert store.load() == app.opts.theme
        assert app.win.theme == app.opts.theme
    finally:
        app.win.stop_curses()


def test_l_text_screens_replace_their_body_and_pop_with_escape():
    _module, app, _backend = _app('l-text-screens')
    try:
        app.draw_once()
        app.main.info_screen_ACTION()
        assert app.stack.curr.name == 'InfoScreen'
        app.draw_once()
        assert app.win.head.texts[0] == 'READ-ONLY DETAIL'
        assert any('Prime rows' in text for text in app.win.body.texts)

        app.handle_key(27)  # the default escape_ACTION pops the read-only screen
        app.stack.perform_actions(app.spin)
        assert app.stack.curr.name == 'TextMainScreen'
    finally:
        app.win.stop_curses()


def test_o_large_bodies_add_every_row_without_dropping():
    _module, app, _backend = _app('o-large-bodies')
    try:
        app.draw_once()
        assert app.win.body.row_cnt >= 2000
        assert app.win.rows_dropped == 0
        assert app.win.opts.max_rows is not None
    finally:
        app.win.stop_curses()
