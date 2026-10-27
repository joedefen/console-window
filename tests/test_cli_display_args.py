"""The argparse boilerplate: --ascii, --ascii=BOOL, --glyphs and --theme."""

import argparse

import pytest

from console_window import Theme, cli
from console_window.glyphs import is_ascii


class _Stream:
    def __init__(self, encoding='utf-8'):
        self.encoding = encoding


@pytest.fixture(autouse=True)
def _forget_the_process_theme(monkeypatch):
    monkeypatch.setattr(Theme, '_current', None)


def _parser():
    return cli.add_display_arguments(argparse.ArgumentParser(prog='demo'))


def _apply(argv, capsys, environ=None):
    args = _parser().parse_args(argv)
    report = cli.apply_display_arguments(
        args,
        prog='demo',
        environ=environ or {'TERM': 'xterm-256color'},
        stream=_Stream(),
    )
    return args, report, capsys.readouterr().out


def test_absent_switches_mean_detect():
    args = _parser().parse_args([])
    assert args.ascii is None
    assert args.glyphs is None
    assert cli.resolve_force_ascii(args) is None


def test_a_bare_ascii_switch_forces_the_fallback():
    args = _parser().parse_args(['--ascii'])
    assert args.ascii is True
    assert cli.resolve_force_ascii(args) is True


@pytest.mark.parametrize('value', ['no', 'NO', 'false', '0', 'off'])
def test_ascii_accepts_an_explicit_no(value):
    args = _parser().parse_args([f'--ascii={value}'])
    assert args.ascii is False
    assert cli.resolve_force_ascii(args) is False


@pytest.mark.parametrize('value', ['yes', 'TRUE', '1', 'on'])
def test_ascii_accepts_an_explicit_yes(value):
    args = _parser().parse_args([f'--ascii={value}'])
    assert cli.resolve_force_ascii(args) is True


def test_an_unparseable_ascii_value_exits():
    with pytest.raises(SystemExit):
        _parser().parse_args(['--ascii=maybe'])


def test_glyphs_is_the_symmetric_switch():
    args = _parser().parse_args(['--glyphs=unicode'])
    assert cli.resolve_force_ascii(args) is False
    args = _parser().parse_args(['--glyphs=ascii'])
    assert cli.resolve_force_ascii(args) is True
    args = _parser().parse_args(['--glyphs=auto'])
    assert cli.resolve_force_ascii(args) is None


def test_glyphs_wins_over_ascii_when_both_are_given():
    args = _parser().parse_args(['--ascii', '--glyphs=unicode'])
    assert cli.resolve_force_ascii(args) is False


def test_the_theme_choices_are_the_known_themes():
    with pytest.raises(SystemExit):
        _parser().parse_args(['--theme=not-a-theme'])


def test_apply_sets_the_mode_and_prints_the_notes(capsys):
    _args, report, out = _apply(['--ascii'], capsys)
    assert report.ascii_mode is True
    assert is_ascii() is True
    assert out.splitlines()
    assert out.startswith('demo: ')


def test_apply_detects_when_no_switch_is_given(capsys):
    _args, report, out = _apply([], capsys, environ={'TERM': 'dumb'})
    assert report.ascii_mode is True
    assert report.source == 'auto'
    assert 'demo: ' in out


def test_apply_seeds_the_theme_for_the_first_window(capsys):
    _apply(['--theme=gruvbox'], capsys)
    assert Theme.get_current() == 'gruvbox'


def test_apply_keeps_the_default_for_an_unknown_theme(capsys):
    args = argparse.Namespace(ascii=None, glyphs=None, theme='nonsense')
    cli.apply_display_arguments(args, environ={'TERM': 'xterm'}, stream=_Stream())
    out = capsys.readouterr().out
    assert 'unknown theme' in out
    assert Theme.get_current() is None


def test_apply_tolerates_a_namespace_without_display_attributes(capsys):
    report = cli.apply_display_arguments(
        argparse.Namespace(), environ={'TERM': 'xterm'}, stream=_Stream())
    assert report.ascii_mode is False
    assert 'font check' in capsys.readouterr().out


def test_the_theme_store_note_only_promises_what_is_true():
    parser = cli.add_display_arguments(argparse.ArgumentParser(prog='demo'))
    theme_help = next(
        action.help for action in parser._actions if action.dest == 'theme')
    assert 'remembered' not in theme_help

    parser = cli.add_display_arguments(argparse.ArgumentParser(prog='demo'),
                                       theme_store=object())
    theme_help = next(
        action.help for action in parser._actions if action.dest == 'theme')
    assert 'remembered' in theme_help
