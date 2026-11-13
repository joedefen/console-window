"""The machine-readable feature-to-demo owner map.

One learning objective belongs to exactly one demo.  A feature added or changed
in the library must update its owning demo and this map; the changelog bullet
names the demo.  ``tests/test_demos.py`` enforces uniqueness, existence and the
per-demo ``Owns:`` docstring line, and compares the rendered table below with
the appendix in ``docs/DEMO-APPS.md``.

Run ``./demos/run-demo features`` (or ``python demos/features.py``) to print the
same table at the terminal.
"""

from __future__ import annotations

#: Demo short names, in curriculum order.
DEMO_ORDER: tuple[str, ...] = (
    'a-basic',
    'b-stack',
    'c-options',
    'd-pick',
    'e-search',
    'f-prompts',
    'g-dialogs',
    'h-messages',
    'i-headers',
    'j-themes',
    'k-glyphs',
    'l-text-screens',
    'm-own-keys',
    'n-suspend',
    'o-large-bodies',
    'p-key-debug',
)

#: feature key -> demo short name.  The key names a learning objective, not an
#: API symbol; see docs/DEMO-APPS.md for the rationale.
FEATURES: dict[str, str] = {
    'abut': 'd-pick',
    'action-dispatch': 'c-options',
    'alert-dialog': 'g-dialogs',
    'answer-dialog': 'g-dialogs',
    'app-loop': 'a-basic',
    'basic-text-screen': 'l-text-screens',
    'begin-prompt': 'f-prompts',
    'caret-editing': 'g-dialogs',
    'context-metadata': 'd-pick',
    'ctrl-c-key': 'b-stack',
    'decor-rows': 'd-pick',
    'demo-mode': 'p-key-debug',
    'escape-action': 'l-text-screens',
    'external-program': 'n-suspend',
    'flash': 'h-messages',
    'glyph-catalog': 'k-glyphs',
    'glyph-cli': 'k-glyphs',
    'glyph-fallback': 'k-glyphs',
    'glyph-help': 'k-glyphs',
    'glyph-vocabulary': 'k-glyphs',
    'header-band': 'a-basic',
    'header-modes': 'i-headers',
    'header-tokens': 'i-headers',
    'help-labels': 'm-own-keys',
    'help-paragraphs': 'l-text-screens',
    'help-screen': 'c-options',
    'incremental-search': 'e-search',
    'inline-confirmation': 'g-dialogs',
    'large-body': 'o-large-bodies',
    'live-data': 'a-basic',
    'max-rows': 'o-large-bodies',
    'min-size': 'o-large-bodies',
    'mono-theme': 'j-themes',
    'navigation': 'a-basic',
    'option-scope': 'c-options',
    'paged-navigation': 'm-own-keys',
    'passthrough-mode': 'e-search',
    'per-screen-state': 'b-stack',
    'per-window-theme': 'j-themes',
    'pick-mode': 'd-pick',
    'pick-range': 'd-pick',
    'pick-size': 'd-pick',
    'prompt-callbacks': 'f-prompts',
    'prompt-placement': 'f-prompts',
    'read-only-screen': 'l-text-screens',
    'redraw-recovery': 'o-large-bodies',
    'scoped-escape': 'e-search',
    'screen-stack': 'b-stack',
    'scroll-indicator': 'o-large-bodies',
    'semantic-attrs': 'j-themes',
    'single-key-prompt': 'f-prompts',
    'span-styling': 'i-headers',
    'spinner-nav-keys': 'm-own-keys',
    'spinner-options': 'c-options',
    'status-levels': 'h-messages',
    'status-lifecycle': 'h-messages',
    'status-placement': 'h-messages',
    'suspend-resume': 'n-suspend',
    'taken-nav-keys': 'm-own-keys',
    'temp-handled-keys': 'e-search',
    'text-prompt': 'f-prompts',
    'textwidth': 'p-key-debug',
    'theme-captions': 'j-themes',
    'theme-picker': 'j-themes',
    'theme-store': 'j-themes',
    'validated-prompt': 'c-options',
    'wide-characters': 'p-key-debug',
}


def owned_by(demo: str) -> list[str]:
    """The sorted feature keys a demo owns."""
    return sorted(key for key, owner in FEATURES.items() if owner == demo)


def render_table() -> str:
    """Render the reverse index in the exact form the documentation uses."""
    lines = [
        '| Feature key | Demo |',
        '| ----------- | ---- |',
    ]
    lines.extend(f'| `{key}` | `{demo}` |'
                 for key, demo in sorted(FEATURES.items()))
    return '\n'.join(lines)


def main() -> None:
    print(render_table())


if __name__ == '__main__':
    main()
