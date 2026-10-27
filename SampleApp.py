#!/usr/bin/env python3
# python: disable=invalid-name

import curses as cs
import sys
import time
import traceback
from types import SimpleNamespace

from console_window import (
    BasicHelpScreen,
    BasicTextScreen,
    ConsoleWindow,
    ConsoleWindowOpts,
    Context,
    HeaderLine,
    IncrementalSearchBar,
    OptionSpinner,
    Screen,
    ScreenStack,
    Theme,
)
from console_window import help as help_text

#: The demo's own vocabulary: a glyph the library does not know about.  It is
#: handed to the window (not registered globally) to show the option route; the
#: registered fallback means ``\u2713`` degrades to ``OK`` automatically.
DEMO_GLYPHS = {'tick': ('\u2713', 'OK')}
DEMO_PROBE = ('tick', 'cursor', 'choice', 'scroll_prev', 'scroll_next')

# Screen IDs
MAIN_ST = 0
HELP_ST = 1
HISTORY_ST = 2
THEME_ST = 3
SCREEN_NAMES = ('MAIN', 'HELP', 'HISTORY', 'THEMES')


class SampleApp:
    def __init__(self, backend=None, singleton=True):
        self.win = None
        self.spin = None
        self.stack = None
        self.items = []  # Items to display in main screen
        self.filter_text = ''
        self.selected_items = set()  # Track "selected" items for demo
        self.operation_count = 0
        # In-place prompt state.  PromptLine itself lives on the window; these
        # are the application's product decisions about which row/item a live
        # prompt belongs to (the window deliberately never learns that).
        self.prompt_item = None
        self.note_item = None
        self.notes = {}

        # Incremental search bar
        self.filter_bar = IncrementalSearchBar(
            on_change=self._on_filter_change,
            on_accept=self._on_filter_accept,
            on_cancel=self._on_filter_cancel
        )

        # IMPORTANT: Create opts BEFORE ScreenStack to ensure proper object linking
        # The OptionSpinner will use stack.obj, so it must be set correctly from the start
        self.opts = SimpleNamespace()

        # Create screen instances
        screens = self.screens = {
            MAIN_ST: MainScreen(self),
            HELP_ST: HelpScreen(self),
            HISTORY_ST: HistoryScreen(self),
            THEME_ST: ThemeScreen(self),
        }

        # Configure console window
        win_opts = ConsoleWindowOpts(
            head_line=True,
            # Symbol set: one app glyph plus the font check the HELP screen shows.
            glyphs=DEMO_GLYPHS,
            glyphs_probe=DEMO_PROBE,
            # No row sizing needed: the pads are viewport-sized and rows live in
            # the model, so the 'z' stress mode's 2000 filler rows need no
            # option.  max_rows is only a safety ceiling (32767 by default).
            min_cols_rows=(60,10),
            pick_attr=cs.A_REVERSE,
            # Ctrl-C arrives as an ordinary key code (bound to 'quit' below)
            # instead of tearing down curses.
            ctrl_c_terminates=False,
        )

        self.win = ConsoleWindow(opts=win_opts, backend=backend, singleton=singleton)
        # Pass self.opts as spins_obj so stack.obj points to the right object
        self.stack = ScreenStack(self.win, self.opts, SCREEN_NAMES, screens)

        # Setup option spinner - it will inherit stack.obj (self.opts)
        spin = self.spin = OptionSpinner(stack=self.stack)
        themes = Theme.list_all()

        # Add view mode and sort options
        # NOTE: settings shown on the HELP screen are scoped to HELP_ST as well,
        # so their spinner keys keep working while help is open.
        spin.add_key('quit', 'q,CTL-C - quit', genre='action', keys={0x3, ord('q')})
        spin.add_key('escape', 'ESC,ENTER - back',
                     keys=[27,10,cs.KEY_ENTER], genre='action')
        spin.add_key('view_mode', 'v - view mode',
                     vals=['compact', 'detailed', 'full'], scope={MAIN_ST, HELP_ST})
        spin.add_key('sort_by', 's - sort by',
                     vals=['name', 'uid', 'home'], scope={MAIN_ST, HELP_ST})
        spin.add_key('theme', 't - theme', vals=themes, scope={THEME_ST, HELP_ST})

        # Add navigation keys (global)
        spin.add_key('help_screen', '? - help', genre='action', scope={MAIN_ST})
        spin.add_key('history_screen', 'h - history', genre='action', scope={MAIN_ST})
        spin.add_key('theme_screen', 't - Theme Screen', genre='action', scope={MAIN_ST})

        # Add main screen actions
        spin.add_key('filter', '/ - filter', genre='action', scope={MAIN_ST})
        spin.add_key('clear_filter', 'ESC - clear filter',
                     keys=[27], genre='action', scope=MAIN_ST)
        spin.add_key('select', 'SPACE - select', keys=[ord(' ')],
                     genre='action', scope={MAIN_ST})
        spin.add_key('answer_demo', 'a - answer demo',
                     genre='action', scope={MAIN_ST})
        spin.add_key('alert_demo', 'l - alert demo',
                     genre='action', scope={MAIN_ST})
        # In-place, buffered prompt rendered as a header row (see note_ACTION).
        spin.add_key('note', 'N - add a note', genre='action', scope={MAIN_ST})
        spin.add_key('show_keys', 'K - show keys (demo mode)', genre='action')

        # Folded in from the retired dev self-test.
        # Scoped to MAIN and HELP, like view_mode/sort_by, so the keys keep
        # working while the help screen is open.
        spin.add_key('pick_size', 'p - rows per pick', vals=[1, 2, 3],
                     scope={MAIN_ST, HELP_ST})
        spin.add_key('name', 'n - set name', prompt='Your name:',
                     scope={MAIN_ST, HELP_ST})
        spin.add_key('force_redraw', 'r - force full redraw', vals=[False, True],
                     scope={MAIN_ST, HELP_ST})
        spin.add_key('stress', 'z - stress (2000 filler rows)', vals=[False, True],
                     scope={MAIN_ST, HELP_ST})
        self.win.set_handled_keys(spin.keys)

        # Seed the prompt option so the answer() dialog opens with empty text.
        self.opts.name = ''

        # Load sample data from /etc/passwd
        self._load_sample_data()

    def _load_sample_data(self):
        try:
            with open('/etc/passwd', 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip() and not line.startswith('#'):
                        parts = line.split(':')
                        if len(parts) >= 3:
                            username = parts[0]
                            uid = parts[2]
                            home = parts[5] if len(parts) > 5 else ''
                            self.items.append({
                                'username': username,
                                'uid': uid,
                                'home': home,
                                'line': line.strip()
                            })
        except Exception:  # pylint: disable=broad-exception-caught
            # The example must run on any host: a malformed/absent passwd file
            # is not an error worth aborting the demo for, so fall back to the
            # fixed sample rows below.
            self.items = [
                {'username': 'demo1', 'uid': '1001', 'home': '/home/demo1',
                 'line': 'demo1:x:1001:1001::/home/demo1:/bin/bash'},
                {'username': 'demo2', 'uid': '1002', 'home': '/home/demo2',
                 'line': 'demo2:x:1002:1002::/home/demo2:/bin/bash'},
                {'username': 'test', 'uid': '1003', 'home': '/home/test',
                 'line': 'test:x:1003:1003::/home/test:/bin/bash'},
            ]

    def _on_filter_change(self, text):
        self.filter_text = text.lower()

    def _on_filter_accept(self, text):
        self.filter_text = text.lower()
        self.win.passthrough_mode = False
        self.win.pick_pos = 0  # Move to top

    def _on_filter_cancel(self, original_text):
        self.filter_text = original_text.lower() if original_text else ''
        self.win.passthrough_mode = False

    def handle_key(self, key):
        # A live in-place prompt owns every key.  This is the documented
        # contract: nothing underneath the prompt (filter, spinner actions)
        # may fire until the prompt has been dealt with.
        if self.win.prompt_active:
            self.win.handle_prompt_key(key)
            return None

        # Handle filter bar NEXT (highest priority when active)
        if self.filter_bar.is_active:
            if self.filter_bar.handle_key(key):
                return None  # Key was consumed

        # Handle ENTER for screen navigation
        if key in (cs.KEY_ENTER, 10):
            if self.stack.curr.num != MAIN_ST:
                self.stack.pop()
                return None

        # Handle spinner keys LAST (normal priority)
        if key in self.spin.keys:
            self.spin.do_key(key, self.win)

        return None

    def get_filtered_items(self):
        if not self.filter_text:
            return self.items
        return [item for item in self.items
                if self.filter_text in item['username'].lower() or
                   self.filter_text in item['home'].lower()]

    def main_loop(self):
        while True:
            current_screen = self.screens[self.stack.curr.num]
            current_screen.draw_screen()
            # redraw=True forces the full-repaint recovery path (toggled by 'r').
            self.win.render(redraw=self.opts.force_redraw)

            key = self.win.prompt(seconds=3.0)
            if key:
                self.handle_key(key)
            self.stack.perform_actions(self.spin)
            self.win.clear()


class DemoScreen(Screen):
    app: SampleApp

    def __init__(self, name, app):  # pylint: disable=unused-argument
        # ``name`` is part of the screen protocol (ThemeScreen passes 'THEMES'),
        # but Screen identifies a screen by its stack number, not a label.
        super().__init__(app)
        self.app = app

    def get_spinner(self):
        return self.app.spin if hasattr(self.app, 'spin') else None

    def escape_ACTION(self):
        app = self.app
        app.stack.pop()

    def quit_ACTION(self):
        app = self.app
        win = app.win

        if app.operation_count > 0:
            win.flash(
                f'Processed {app.operation_count} items. Goodbye!',
                duration=1.5
            )
            time.sleep(1.5)
        win.stop_curses()
        sys.exit(0)

class MainScreen(DemoScreen):
    header_cnt = 0
    def __init__(self, app):
        super().__init__('MAIN', app)

    def draw_screen(self):
        self.app.win.set_pick_mode(True, self.app.opts.pick_size)

        self._draw_body()
        self._draw_header()

    def _draw_body(self):
        app = self.app
        items = app.get_filtered_items()
        by = app.opts.sort_by
        by = 'username' if by == 'name' else by
        items = sorted(items, key=lambda it: it[by])
        view_mode = app.opts.view_mode
        for item in items:
            username = item['username']
            uid = item['uid']
            home = item['home']

            # Determine status and color
            if username in app.selected_items:
                status = '✓ Processed'
                attr = cs.color_pair(Theme.SUCCESS)
            else:
                status = '  Ready'
                attr = cs.color_pair(0)

            # Format line based on view mode
            if view_mode == 'full':
                line = f'{username:<16} {uid:<8} {home:<30} {status}'
            elif view_mode == 'detailed':
                line = f'{username:<16} {uid:<8} {status}'
            else:  # compact
                line = f'{username:<20} {status}'

            # Create context for picking
            ctx = Context(genre='item', item=item)
            app.win.add_body(line, attr=attr, context=ctx)

            # Draw the in-place confirmation right after the row it belongs to.
            # The wording and warning glyph stay here (product decisions); the
            # window's prompt helper owns the display composition and marks both
            # rows TRANSIENT/non-pickable for us.
            if app.win.prompt_active and app.prompt_item == username:
                app.win.add_prompt_lines(
                    attr=cs.color_pair(Theme.WARNING) | cs.A_BOLD,
                    hint_attr=cs.A_DIM,
                )

        if app.opts.stress:
            # Non-pickable filler: exercises large pads and the scroll indicator,
            # and shows DECOR rows being skipped by navigation.
            for extra in range(2000):
                app.win.add_body(f'  filler {extra + 1}', attr=cs.A_DIM,
                                 context=Context(genre='DECOR'))

    def _draw_header(self):
        app = self.app
        # Build the header explicitly from HeaderLine tokens: intent is declared,
        # so nothing here can be misread as markup.
        line = HeaderLine()
        line.text('  ')
        bar_line = app.filter_bar.as_header_line(prefix='/')
        if bar_line:
            line.extend(bar_line)
        else:
            line.text('/')

        header_test = self.header_cnt % 3
        self.header_cnt += 1

        # Show spinner keys.
        #
        # Every key below is spelled with bracket_key(), because the third
        # strategy round-trips the line through str() and the legacy string
        # scanner, which only knows two KEY spellings: '[x]' (exactly one
        # character between brackets) and 'UPPERCASE:' (one or more capitals
        # followed by a colon).  An unbracketed key('l') or key('?') keeps its
        # KEY role in the token paths, but str(line) is just text: 'l:alrtDemo'
        # and '?:help' fail both legacy rules, so the re-parse would render the
        # same characters with no styling.  Bracket-spelling them makes all
        # three strategies produce the same runs.  (key('SPC') is fine: it is
        # the 'UPPERCASE:' form.)
        line.text(' ').bracket_key('v').text(f'iew={app.opts.view_mode}')
        line.text(' ').bracket_key('s').text(f'ort={app.opts.sort_by}')
        line.text(' ').bracket_key('a').text('nsDemo')
        line.text(' ').bracket_key('l').text(':alrtDemo')
        line.text(' ').key('SPC').text(':process')
        # line.text(' ').bracket_key('p').text(f'ick={app.opts.pick_size}')
        line.text(' ').bracket_key('n').text(f'ame={app.opts.name or "-"}')
        line.text(' ').bracket_key('N').text(':note')
        # line.text(' ').key('r').text('edraw')
        # line.text(' ').key('z').text(':stress')
        # line.text(' ').bracket_key('t').text('hemes')
        # line.text(' ').bracket_key('h').text('ist')
        line.text(' ').bracket_key('?').text(':help')
        if header_test == 0:  # tokens, emitted verbatim (brackets are literal)
            app.win.add_header_line(line, mode='Underline')
        elif header_test == 1:  # tokens, brackets treated as markup only
            app.win.add_fancy_header(line, mode='Underline')
        else:  # str(line) re-parsed by the legacy scanner (lossy by design)
            app.win.add_fancy_header(str(line), mode='Underline')

        # Column headers
        view_mode = app.opts.view_mode
        if view_mode == 'full':
            header = f'{"User":<16} {"UID":<8} {"Home":<30} Status'
        elif view_mode == 'detailed':
            header = f'{"User":<16} {"UID":<8} Status'
        else:  # compact
            header = f'{"User":<20} Status'

        app.win.add_header(header, attr=cs.A_DIM | cs.A_UNDERLINE)

        # A buffered note prompt is a screen-wide question, so it lives in the
        # header band rather than under one row.  add_prompt_header() renders
        # the library's fixed ': buffer│' format.
        if app.win.prompt_active and app.note_item:
            app.win.add_prompt_header()

    def filter_ACTION(self):
        app = self.app
        app.filter_bar.start(app.filter_text)
        app.win.passthrough_mode = True

    def clear_filter_ACTION(self):
        app = self.app
        # IncrementalSearchBar exposes only a read-only ``text`` property, so
        # the example resets the buffer directly rather than growing the widget
        # API for a single demo action.
        app.filter_bar._text = ''  # pylint: disable=protected-access
        app.filter_text = ''
        app.win.pick_pos = 0
        app.win.status('Filter cleared', timeout=1.0)

    def select_ACTION(self):
        app = self.app
        win = app.win
        ctx = win.get_picked_context()
        if not ctx or not hasattr(ctx, 'item'):
            return
        username = ctx.item['username']
        app.prompt_item = username

        def confirm(_answer):
            app.prompt_item = None
            app.selected_items.add(username)
            app.operation_count += 1
            # Non-modal: the listing stays visible on the next render.
            win.status(f'✓ Processed {username}', timeout=1.5)

        def cancel():
            app.prompt_item = None
            win.status('Cancelled', timeout=1.0)

        # Single-key mode 'y'; the window enables passthrough for us and the
        # callbacks run after the prompt is gone (so status() is safe here).
        win.begin_prompt(
            f'    ⚠️  Process {username}?',
            mode='y',
            hint='Marks the row as ✓ Processed',
            on_confirm=confirm,
            on_cancel=cancel,
        )

    def note_ACTION(self):
        app = self.app
        win = app.win
        ctx = win.get_picked_context()
        if not ctx or not hasattr(ctx, 'item'):
            win.status('Select an item first', level='warn', timeout=2.0)
            return
        username = ctx.item['username']
        app.note_item = username

        def save(answer):
            app.note_item = None
            app.notes[username] = answer
            win.status(f'✓ Note saved for {username}', level='warn',
                       timeout=2.0)

        def cancel():
            app.note_item = None
            win.status('Note cancelled', timeout=1.5)

        # Buffered text mode.  add_prompt_header() draws it in the header band,
        # including the caret glyph and the fixed ': ' separator.
        win.begin_prompt(
            f'Note for {username}',
            hint='ENTER to save, ESC to cancel',
            mode='text',
            seed=app.notes.get(username, ''),
            on_confirm=save,
            on_cancel=cancel,
        )

    def answer_demo_ACTION(self):
        app = self.app
        win = app.win
        response = win.answer('Enter your name (or ESC to cancel): ',
                              height=1)
        if response:
            win.status(f'Hello, {response}!', level='warn', timeout=2.0)
        else:
            win.status('Cancelled', timeout=1.0)

    def alert_demo_ACTION(self):
        ctx = self.app.win.get_picked_context()
        if ctx and hasattr(ctx, 'item'):
            item = ctx.item
            # alert() displays a single-paragraph message (newlines are ignored)
            # Keep it simple and short
            message = (
                f"Selected user: {item['username']} "
                f"(UID: {item['uid']}) "
                f"Home: {item['home']}"
            )
            self.app.win.alert(message, title='User Info')
        else:
            self.app.win.alert(
                'No item selected! Please select an item from the list first.',
                title='Selection Required'
            )

    def help_screen_ACTION(self):
        self.app.stack.push(HELP_ST, self.app.win.pick_pos)

    def history_screen_ACTION(self):
        app = self.app
        win = app.win
        app.stack.push(HISTORY_ST, win.pick_pos)

    def theme_screen_ACTION(self):
        app = self.app
        win = app.win
        app.stack.push(THEME_ST, win.pick_pos)

    def show_keys_ACTION(self):
        """ Show last key for demo"""
        self.app.win.set_demo_mode(enabled=None) # toggle it


class HelpScreen(DemoScreen, BasicHelpScreen):
    # Show the library's font-check / ASCII-fallback note under our own text.
    show_display_notes = True

    def __init__(self, app):
        super().__init__('HELP', app)

    def extra_help_paragraphs(self):
        return (help_text.theme_paragraph(open_key='T', cycle_key='t'),)

#   def draw_screen(self):
#       app = self.app
#       app.win.set_pick_mode(False)

#       spinner = self.get_spinner()
#       if spinner:
#           # Use built-in help display
#           spinner.show_help_nav_keys(app.win)
#           spinner.show_help_body(app.win)


class HistoryScreen(DemoScreen):
    def __init__(self, app):
        super().__init__('HISTORY', app)
        # Constructed before the ConsoleWindow exists, exactly like the other
        # screens: BasicTextScreen resolves app.win at draw time.
        self.text_screen = BasicTextScreen(app)

    def draw_screen(self):
        app = self.app
        lines = [('  Press ESC or ENTER to return', cs.A_DIM), '']
        if app.selected_items:
            lines.append(f'Total processed items: {len(app.selected_items)}')
            lines.append('')
            for username in sorted(app.selected_items):
                # Find the item details
                item = next((i for i in app.items
                           if i['username'] == username), None)
                if item:
                    line = (f'  ✓ {username:<16} uid={item["uid"]:<8} '
                            f'{item["home"]}')
                    lines.append((line, cs.color_pair(Theme.SUCCESS)))
        else:
            lines.extend([
                'No items have been processed yet.',
                '',
                'Go back to the main screen and press SPACE on an item '
                'to process it.',
            ])
        # Content is rebuilt each draw; nothing is cached across frames.
        self.text_screen.set_text(lines, head=['OPERATION HISTORY'])
        self.text_screen.draw_screen()


class ThemeScreen(Theme.create_picker_screen(DemoScreen, cycle_key='t')):
    """THEMES screen supplied by Theme.create_picker_screen()."""

    def __init__(self, app):
        super().__init__('THEMES', app)

def main(backend=None, singleton=True):
    # The same two lines every console-window app needs for --ascii/--theme.
    import argparse

    from console_window import cli

    parser = cli.add_display_arguments(argparse.ArgumentParser(prog='SampleApp'))
    opts = parser.parse_args()
    cli.apply_display_arguments(opts, prog='SampleApp')

    try:
        app = SampleApp(backend=backend, singleton=singleton)
        app.main_loop()
    except Exception as bummer:  # pylint: disable=broad-exception-caught
        # Top-level demo guard: no matter how the app failed, leave the terminal
        # usable and show the error instead of dying with a broken screen.
        win = ConsoleWindow.primary_window()
        if win:
            win.stop_curses()
        print('exception: ', str(bummer))
        print(traceback.format_exc())

if __name__ == '__main__':
    main()
