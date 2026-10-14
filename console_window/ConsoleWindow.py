#!/usr/bin/env python3
"""Compatibility facade for :mod:`console_window`.

Historically this module held the entire implementation.  It has been split
into focused modules (``window``, ``theme``, ``context``, ``opts``, ``widgets``,
``spinner``, ``screens``, ``keys``, ``signals``, ``geometry``); this module
re-exports the public names so existing imports keep working::

    from console_window import ConsoleWindow, OptionSpinner, ...
    from console_window.ConsoleWindow import ConsoleWindow, OptionSpinner, ...

Running ``python -m console_window.ConsoleWindow`` still launches the original
interactive self-test.
"""

import sys
import time
import traceback

from .context import Context
from .keys import NAVIGATION_KEYS
from .opts import ConsoleWindowOpts
from .screens import HOME_ST, BasicHelpScreen, Screen, ScreenStack
from .spinner import OptionSpinner
from .theme import Theme
from .widgets import IncrementalSearchBar, InlineConfirmation
from .window import ConsoleWindow

__all__ = [
    'HOME_ST',
    'NAVIGATION_KEYS',
    'BasicHelpScreen',
    'ConsoleWindow',
    'ConsoleWindowOpts',
    'Context',
    'IncrementalSearchBar',
    'InlineConfirmation',
    'OptionSpinner',
    'Screen',
    'ScreenStack',
    'Theme',
]

dump_str = None


if __name__ == '__main__':
    def main() -> None:
        """Test program"""
        def do_key(key: int) -> object:
            nonlocal spin, win, opts, pick_values
            value = spin.do_key(key, win)
            if key in (ord('p'), ord('s')):
                win.set_pick_mode(on=opts.pick_mode, pick_size=opts.pick_size)
                if not opts.pick_mode:
                    opts.prev_pick = pick_values[win.pick_pos//win.pick_size]
            elif key == ord('n'):
                win.alert(title='Info', message=f'got: {value}')
            elif opts.quit:
                opts.quit = False
                sys.exit(key)
            return value

        spin = OptionSpinner()
        spin.add_key('help_mode', '? - toggle help screen', vals=[False, True])
        spin.add_key('pick_mode', 'p - toggle pick mode, turn off to pick current line', vals=[False, True])
        spin.add_key('pick_size', 's - #rows in pick', vals=[1, 2, 3])
        spin.add_key('name', 'n - select name', prompt='Provide Your Name:')
        spin.add_key('mult', 'm - row multiplier', vals=[0.5, 0.9, 1.0, 1.1, 2, 4, 16])
        spin.add_key('quit', 'q,CTL-C - quit the app', genre='action', keys={0x3, ord('q')})
        opts = spin.default_obj

        console_opts = ConsoleWindowOpts()
        console_opts.head_line = True
        console_opts.keys = spin.keys
        console_opts.ctrl_c_terminates = False
        console_opts.body_rows = 4000
        console_opts.answer_show_redraws = True
        win = ConsoleWindow(opts=console_opts)

        opts.name = ""
        opts.prev_pick = 'n/a'
        pick_values = []
        for loop in range(100000000000):
            body_size = round(win.scroll_view_size*opts.mult)
            # body_size = 4000 # temp to test scroll pos indicator when big
            if opts.help_mode:
                win.set_pick_mode(False)
                spin.show_help_nav_keys(win)
                spin.show_help_body(win)
            else:
                win.set_pick_mode(opts.pick_mode, opts.pick_size)
                win.add_header(f'{time.monotonic():.3f} [p]ick={opts.pick_mode}'
                            + f' s:#rowsInPick={opts.pick_size} [n]ame [m]ult={opts.pick_size} ?=help [q]uit')
                win.add_header(f'Header: {loop} name="{opts.name}"  {opts.prev_pick=}')
                pick_values = []
                for idx, line in enumerate(range(body_size//opts.pick_size)):
                    value = f'{loop}.{line}'
                    win.add_body(f'Main pick: {value}')
                    pick_values.append(value)
                    for num in range(1, opts.pick_size):
                        win.draw(num+idx*opts.pick_size, 0, f'  addon: {loop}.{line}')
            win.render(redraw=bool(loop%2))
            _ = do_key(win.prompt(seconds=5))
            win.clear()

    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exce:
        win = ConsoleWindow.primary_window()
        if win:
            win.stop_curses()
        print("exception:", str(exce))
        print(traceback.format_exc())
        if dump_str:
            print(dump_str)
