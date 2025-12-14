
# console-window 

**A robust and feature-rich wrapper for the standard Python `curses` library, simplifying the creation of complex, full-screen Text User Interface (TUI) applications.**

This package abstracts away the complexities of managing curses pads, dynamic screen resizing, custom scroll/pick synchronization, and keyboard handling, allowing developers to focus purely on content.

## Installation

Install the package via `pip`:

```bash
pip install console-window
```

## Core Features (The "Secret Sauce")

The wrapper handles several advanced terminal interaction patterns automatically:

  * **Padded Content Management:** Uses separate `head` and `body` pads, allowing for a static header area while the main content area can be scrolled independently.
  * **Seamless Resizing:** Automatically detects terminal size changes (`KEY_RESIZE`) and recalculates layout dimensions, with robust error handling to prevent common `curses.error` crashes during resizing.
  * **Scroll & Pick Synchronization:** The `Window` class manages **scroll position** and a separate **pick position** (highlighted row) simultaneously.
    * When using pick mode, scrolling automatically tracks the highlighted element to keep it visible in `.pick_pos`.
    * To use that value, you must separately be able to associate `.pick_pos` to its value by, say, keeping an array of values for every added line to the `body`. 
  * **Intuitive Navigation:** Provides built-in handling for common navigation keys (`j`/`k`, `UP`/`DOWN`, Page Up/Down, `H`/`M`/`L` for home/middle/last viewable line, etc.).
  * **Dynamic Options Management (`OptionSpinner`):** The companion class simplifies creation of application settings, allowing users to **toggle options** or input strings using single keypresses (e.g., `p` to toggle pick mode).
  * **Blocking Popups:** Includes fully implemented, blocking pop-up methods for user input (`.answer()`) and alerts (`.alert()`), handling the necessary temporary screen takeover and cursor management.

## Minimal Working Example

This example demonstrates setting up the window, using the `OptionSpinner` for control, and running the main render/prompt loop.

```
import curses
from console_window import ConsoleWindow, ConsoleWindowOpts, OptionSpinner

def main_app_loop(stdscr):
    # 1. Setup Options Manager
    spin = OptionSpinner()
    opts = spin.default_obj  # Access options via this namespace

    # Add features controlled by keypresses
    spin.add_key('help_mode', '? - toggle help screen', vals=[False, True])
    spin.add_key('pick_mode', 'p - toggle pick mode', vals=[False, True])
    spin.add_key('pick_size', 's - #rows in pick', vals=[1, 2, 3])
    spin.add_key('name', 'n - select name', prompt='Provide Your Name:')
    spin.add_key('quit', 'q,Q - quit the app', category='action', keys={ord('Q'), ord('q')})

    # 2. Initialize Window with ConsoleWindowOpts
    win_opts = ConsoleWindowOpts(
        head_line=True,
        keys=spin.keys,
        min_cols_rows=(60, 20),
        single_cell_scroll_indicator=True
    )
    win = ConsoleWindow(opts=win_opts)
    opts.name = "[hit 'n' to enter name]"
    loop_count = 0

    while True:
        loop_count += 1
        
        # 3. Add Content
        if opts.help_mode:
            win.set_pick_mode(False)
            spin.show_help_nav_keys(win)
            spin.show_help_body(win)
        else:
            win.set_pick_mode(opts.pick_mode, opts.pick_size)
            win.add_header(f'TUI App Header | Loop: {loop_count} | Name: "{opts.name}"')
            
            # Add body content (scrollable)
            for idx in range(100):
                win.add_body(f'Main Item {idx+1}')

        # 4. Render and Prompt for Input
        win.render()
        key = win.prompt(seconds=0.5)  # Wait for half a second or a keypress

        # 5. Handle Keys (App-specific logic)
        if key is not None:
            # Check if OptionSpinner can handle the key (p, s, n, ?)
            spin.do_key(key, win)
            
            if opts.quit:
                opts.quit = False
                break  # Exit the loop
        
        win.clear()

if __name__ == '__main__':
    try:
        # Note: Window.__init__ starts curses and registers atexit cleanup
        curses.wrapper(main_app_loop)
    except KeyboardInterrupt:
        pass
```


## License
MIT

## Projects Using console-window
For more extensive examples, you can look at some projects using `console-window`:

* [efibootdude](https://github.com/joedefen/efibootdude)
  * simple wrapper for `efibootmgr`
  * one of the smaller projects
  * demonstrates a context sensitive available keys lines (i.e., first line) where the actions depend on current line.
* [dwipe](https://github.com/joedefen/dwipe)
  * disk cleaner with parallel jobs and stamps wiped partitions
* [pmemstat](https://github.com/joedefen/pmemstat)
  * system/process memory monitor with rollups and hooks for zRAM
* [memfo](https://github.com/joedefen/memfo)
  * viewer of /proc/meminfo that shows historical values
* [vappman](https://github.com/joedefen/vappman)
  * convenince wrapper to mostly hide CLI of [AppMan](https://github.com/ivan-hc/AppMan), a life-cycle manager for 2000+ AppImages
* [my-snaps](https://github.com/joedefen/my-snaps)
  * special purpose BTRFS snap manager
