#!/usr/bin/env python3
"""
ConsoleWindow Comprehensive Demo

This demo showcases the main features of ConsoleWindow:
- OptionSpinner for cycling through choices and triggering actions
- Screen classes (Main, Help, History, Theme)
- IncrementalSearchBar for inline filtering in header
- InlineConfirmation for inline prompts
- Theme/color support
- Flash and answer methods for user feedback

Usage:
    .venv/bin/python3 demo.py

    Or activate the venv first:
    source .venv/bin/activate
    python3 demo.py

Features demonstrated:
    - Press q to quit
    - Navigate with arrow keys or j/k
    - Press v to cycle view modes (compact/detailed/full)
    - Press s to cycle sort options (name/uid/home)
    - Press / to filter items (inline search bar)
    - Press SPACE to select an item (inline confirmation)
    - Press a to demo the answer() prompt
    - Press l to demo the alert() popup
    - Press ? for help screen
    - Press h for history screen
    - Press t for themes (and cycle themes with t on theme screen)
"""
# python: disable=invalid-name

import sys
import time
import traceback
import curses as cs
from types import SimpleNamespace
from console_window import (
    ConsoleWindow, ConsoleWindowOpts, OptionSpinner,
    IncrementalSearchBar, InlineConfirmation, Theme,
    Screen, ScreenStack, Context
)

# Screen IDs
MAIN_ST = 0
HELP_ST = 1
HISTORY_ST = 2
THEME_ST = 3
SCREEN_NAMES = ('MAIN', 'HELP', 'HISTORY', 'THEMES')


class DemoApp:
    """Main demo application"""
    singleton = None

    def __init__(self):
        DemoApp.singleton = self
        self.win = None
        self.spin = None
        self.stack = None
        self.items = []  # Items to display in main screen
        self.filter_text = ''
        self.selected_items = set()  # Track "selected" items for demo
        self.operation_count = 0

        # Inline confirmation handler
        self.confirmation = InlineConfirmation()

        # Incremental search bar
        self.filter_bar = IncrementalSearchBar(
            on_change=self._on_filter_change,
            on_accept=self._on_filter_accept,
            on_cancel=self._on_filter_cancel
        )
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
            body_rows=200,
            head_rows=4,
            min_cols_rows=(60,10),
            pick_attr=cs.A_REVERSE,
            ctrl_c_terminates=True,
        )

        self.win = ConsoleWindow(opts=win_opts,)
        self.stack = ScreenStack(self.win, None, SCREEN_NAMES, screens)

        # Setup option spinner with add_key
        spin = self.spin = OptionSpinner(stack=self.stack)
        spin.default_obj = self.opts
        themes = Theme.list_all()

        # Add view mode and sort options
        spin.add_key('quit', 'q - quit', genre='action')
        spin.add_key('escape', 'ESC,ENTER - back',
                     keys=[27,10,cs.KEY_ENTER], genre='action')
        spin.add_key('view_mode', 'v - view mode',
                     vals=['compact', 'detailed', 'full'], scope={MAIN_ST})
        spin.add_key('sort_by', 's - sort by',
                     vals=['name', 'uid', 'home'], scope={MAIN_ST})
        spin.add_key('theme', 't - theme', vals=themes, scope={THEME_ST})

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
        self.win.set_handled_keys(spin.keys)



        # Load sample data from /etc/passwd
        self._load_sample_data()

    def _load_sample_data(self):
        """Load sample items from /etc/passwd"""
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
        except Exception:
            # Fallback sample data
            self.items = [
                {'username': 'demo1', 'uid': '1001', 'home': '/home/demo1',
                 'line': 'demo1:x:1001:1001::/home/demo1:/bin/bash'},
                {'username': 'demo2', 'uid': '1002', 'home': '/home/demo2',
                 'line': 'demo2:x:1002:1002::/home/demo2:/bin/bash'},
                {'username': 'test', 'uid': '1003', 'home': '/home/test',
                 'line': 'test:x:1003:1003::/home/test:/bin/bash'},
            ]

    def _on_filter_change(self, text):
        """Update filter as user types"""
        self.filter_text = text.lower()

    def _on_filter_accept(self, text):
        """Filter accepted (ENTER pressed)"""
        self.filter_text = text.lower()
        self.win.passthrough_mode = False
        self.win.pick_pos = 0  # Move to top

    def _on_filter_cancel(self, original_text):
        """Filter cancelled (ESC pressed)"""
        self.filter_text = original_text.lower() if original_text else ''
        self.win.passthrough_mode = False

    def _start_operation(self):
        """Start operation after confirmation"""
        if self.confirmation.partition_name:
            item_name = self.confirmation.partition_name
            # Mark item as "processed"
            self.selected_items.add(item_name)
            self.operation_count += 1
            # Flash success message
            self.win.flash(f'✓ Processed {item_name}', duration=1.5)
        self.confirmation.cancel()
        self.win.passthrough_mode = False

    def handle_key(self, key):
        """Handle global key presses - ORDER MATTERS!"""
        # Handle filter bar FIRST (highest priority when active)
        if self.filter_bar.is_active:
            if self.filter_bar.handle_key(key):
                return None  # Key was consumed

        # Handle confirmation mode SECOND (high priority when active)
        if self.confirmation.active:
            result = self.confirmation.handle_key(key)
            if result == 'confirmed':
                self._start_operation()
            elif result == 'cancelled':
                self.confirmation.cancel()
                self.win.passthrough_mode = False
            return None  # Key was consumed by confirmation

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
        """Get items matching current filter"""
        if not self.filter_text:
            return self.items
        return [item for item in self.items
                if self.filter_text in item['username'].lower() or
                   self.filter_text in item['home'].lower()]

    def do_key(self, key):
        """ TBD """
        if not key:
            return
        # handle Inline confirmation / filter
        if key in self.spin.keys:
            self.spin.do_key(key, self.win)

    def main_loop(self):
        """Main application loop"""

        while True:
            current_screen = self.screens[self.stack.curr.num]
            current_screen.draw_screen()
            self.win.render()

            key = self.win.prompt(seconds=3.0)
            if key:
                self.handle_key(key)
            self.stack.perform_actions(self.spin)
            self.win.clear()


class DemoScreen(Screen):
    """Base screen class for demo screens"""
    app: DemoApp

    def __init__(self, name, app):
        super().__init__(app)
        self.app = app

    def get_spinner(self):
        """Get the option spinner"""
        return self.app.spin if hasattr(self.app, 'spin') else None

    def escape_ACTION(self):
        """ go back """
        app = self.app
        app.stack.pop()

    def quit_ACTION(self):
        """Quit the application"""
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
    """Main screen showing user list"""

    def __init__(self, app):
        super().__init__('MAIN', app)

    def draw_screen(self):
        """Draw main screen with item list"""
        self.app.win.set_pick_mode(True)

        self._draw_body()
        self._draw_header()

    def _draw_body(self):
        """  Display items """
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

            # Show inline confirmation if active for this item
            if app.confirmation.active and \
               app.confirmation.partition_name == username:
                msg = f'    ⚠️  Process {username}?'
                if app.confirmation.mode == 'y':
                    msg += " - Press 'y' or ESC"
                elif app.confirmation.mode == 'Y':
                    msg += " - Press 'Y' or ESC"

                app.win.add_body(
                    msg,
                    attr=cs.color_pair(Theme.WARNING) | cs.A_BOLD,
                    context=Context(genre='DECOR')
                )

    def _draw_header(self):
        app = self.app
        # Build header with filter display
        filter_display = app.filter_bar.get_display_string(prefix='/')
        if not filter_display:
            filter_display = '/'
        app.win.add_header(filter_display, attr=cs.A_BOLD)

        # Show spinner keys
        line = f'[v]iew={app.opts.view_mode}'
        line += f' [s]ort={app.opts.sort_by}'
        line += ' [a]nsDemo'
        line += ' l:alrtDemo'
        line += ' [t]hemes'
        line += ' [h]ist'
        line += ' ?:help'
        app.win.add_header(f'  {line}', attr=cs.A_DIM, resume=True)

        # Column headers
        view_mode = app.opts.view_mode
        if view_mode == 'full':
            header = f'{"User":<16} {"UID":<8} {"Home":<30} Status'
        elif view_mode == 'detailed':
            header = f'{"User":<16} {"UID":<8} Status'
        else:  # compact
            header = f'{"User":<20} Status'

        app.win.add_header(header, attr=cs.A_DIM | cs.A_UNDERLINE)

    def filter_ACTION(self):
        """Activate filter search bar"""
        app = self.app
        app.filter_bar.start(app.filter_text)
        app.win.passthrough_mode = True

    def clear_filter_ACTION(self):
        """Clear filter search bar"""
        app = self.app
        app.filter_bar._text = ''
        app.filter_text = ''
        app.win.pick_pos = 0

    def select_ACTION(self):
        """Select/process the current item with confirmation"""
        app = self.app
        ctx = app.win.get_picked_context()
        if ctx and hasattr(ctx, 'item'):
            item = ctx.item
            username = item['username']
            # Start inline confirmation (mode 'y' = press 'y' to confirm)
            app.confirmation.start('process', username, mode='y')
            app.win.passthrough_mode = True

    def answer_demo_ACTION(self):
        """Demo the answer() method"""
        app = self.app
        win = app.win
        response = win.answer('Enter your name (or ESC to cancel): ',
                              height=1)
        if response:
            win.flash(f'Hello, {response}!', duration=2.0)
        else:
            win.flash('Cancelled', duration=1.0)

    def alert_demo_ACTION(self):
        """Demo the alert() method - shows a simple modal message box"""
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
        """Navigate to help screen"""
        self.app.stack.push(HELP_ST, self.app.win.pick_pos)

    def history_screen_ACTION(self):
        """Navigate to history screen"""
        app = self.app
        win = app.win
        app.stack.push(HISTORY_ST, win.pick_pos)

    def theme_screen_ACTION(self):
        """Navigate to theme screen"""
        app = self.app
        win = app.win
        app.stack.push(THEME_ST, win.pick_pos)


class HelpScreen(DemoScreen):
    """Help screen"""

    def __init__(self, app):
        super().__init__('HELP', app)

    def draw_screen(self):
        """Draw help screen"""
        app = self.app
        app.win.set_pick_mode(False)

        spinner = self.get_spinner()
        if spinner:
            # Use built-in help display
            spinner.show_help_nav_keys(app.win)
            spinner.show_help_body(app.win)


class HistoryScreen(DemoScreen):
    """History screen showing operation log"""

    def __init__(self, app):
        super().__init__('HISTORY', app)

    def draw_screen(self):
        """Draw history screen"""
        app = self.app
        app.win.set_pick_mode(False)

        app.win.add_header('OPERATION HISTORY', attr=cs.A_BOLD)
        app.win.add_header('  Press ESC or ENTER to return',
                          attr=cs.A_DIM, resume=True)

        if app.selected_items:
            app.win.put_body('')
            app.win.put_body(f'Total processed items: {len(app.selected_items)}')
            app.win.put_body('')
            for username in sorted(app.selected_items):
                # Find the item details
                item = next((i for i in app.items
                           if i['username'] == username), None)
                if item:
                    line = f'  ✓ {username:<16} uid={item["uid"]:<8} {item["home"]}'
                    app.win.add_body(line, attr=cs.color_pair(Theme.SUCCESS))
        else:
            app.win.put_body('')
            app.win.put_body('No items have been processed yet.')
            app.win.put_body('')
            app.win.put_body('Go back to the main screen and press '
                           'SPACE on an item to process it.')


class ThemeScreen(DemoScreen):
    """Theme selection screen"""

    def __init__(self, app):
        super().__init__('THEMES', app)

    def draw_screen(self):
        """Draw theme screen with color samples"""
        app = self.app
        win = app.win
        win.set_pick_mode(False)
        if app.opts.theme != Theme.get_current():
            Theme.set(app.opts.theme)

        theme = app.opts.theme
        win.add_header(f'COLOR THEMES: [t]heme={theme}',
                          attr=cs.A_BOLD)
        win.add_header('  ESC:return', attr=cs.A_DIM, resume=True)

        win.put_body('Color samples:')
        win.put_body('')

        # Color samples
        color_samples = [
            (Theme.DANGER, 'DANGER', 'Destructive operations'),
            (Theme.SUCCESS, 'SUCCESS', 'Completed operations'),
            (Theme.WARNING, 'WARNING', 'Warnings and cautions'),
            (Theme.INFO, 'INFO', 'Informational messages'),
            (Theme.EMPHASIS, 'EMPHASIS', 'Emphasized text'),
            (Theme.ERROR, 'ERROR', 'Error messages'),
            (Theme.PROGRESS, 'PROGRESS', 'Progress indicators'),
        ]

        for color_id, label, description in color_samples:
            line = f'  {label:<12} ████████  {description}'
            win.add_body(line, attr=cs.color_pair(color_id))

    def theme_screen(self):
        """Cycle to next theme"""
        themes = Theme.list_all()
        current = Theme.get_current()
        idx = themes.index(current) if current in themes else -1
        next_theme = themes[(idx + 1) % len(themes)]
        Theme.set(next_theme)

def main():
    """Main entry point"""
    try:
        app = DemoApp()
        app.main_loop()
    except Exception as bummer:
        app = DemoApp.singleton
        if app and app.win:
            app.win.stop_curses()
        print('exception: ', str(bummer))
        print(traceback.format_exc())


if __name__ == '__main__':
    main()
