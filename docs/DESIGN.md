# Design system

This document describes the visual language of the desktop application and,
more importantly, the rules that keep it consistent. If you are adding UI,
read the "Rules" section — most of it exists because something broke once.

Everything lives in four modules:

| Module | Responsibility |
| --- | --- |
| `ui/theme.py` | Design tokens, the two palettes, the global stylesheet |
| `ui/icons.py` | The vector icon set, recoloured per theme |
| `ui/components.py` | Small shared widgets built from the tokens |
| `ui/batch_delegate.py` | Custom painting for rows of the batch table |

## Principles

**The work is the interface.** The user is looking at their scans, not at our
chrome. Pages get colour, borders and thumbnails; the surrounding UI stays
quiet — greys, hairlines, and a single accent.

**Every automated decision is visible and reversible.** Anything the analyser
concluded is shown as a state on the page itself, with the evidence that led
to it (ink density, decoded barcode) and a control to overrule it. Nothing is
written to disk until the user confirms.

**Colour carries meaning, never decoration.** A colour in this app always
encodes a page state. If you need to make something "pop" without a state
behind it, use weight or spacing instead.

**Local by default, and it says so.** The `100% LOCAL` badge in the app bar is
a product feature, not a slogan — the app never opens a socket.

## Tokens

Never hardcode a colour, radius or font size. Read it from `theme`:

```python
from pdf_batch_separator.ui import theme

theme.color("muted")          # -> "#667085", follows the active theme
theme.qcolor("line")          # -> QColor, for painting in a delegate
theme.family("separator")     # -> the full accent family dict
theme.SPACE["md"]             # -> 12
theme.RADIUS["lg"]            # -> 11
```

The surface tokens are `canvas`, `surface`, `surface_alt`, `sunken`,
`overlay` and `thumb_bg`; text is `ink`, `muted`, `subtle` and `on_accent`;
lines are `line`, `line_soft` and `line_strong`, plus `focus`, `shadow`,
`scroll` and `scroll_hover`. Spacing runs `xs` 4 → `2xl` 32, and radii run
`sm` 5 → `xl` 14 with `pill` for fully rounded shapes.

Both palettes define exactly the same keys, so a token always resolves in
either theme; a test enforces this. Requesting an unknown token raises rather
than silently returning a default.

### Accent families

Six families — `green`, `blue`, `red`, `amber`, `purple`, `neutral` — each with
the same five shades, plus semantic aliases so call sites read by intent
rather than by hue:

| Alias | Family | Used for |
| --- | --- | --- |
| `success` | green | Kept pages, ready files, the primary action |
| `info` | blue | Selection, informational hints |
| `danger` | red | Blank pages, removals, errors |
| `warning` | amber | Files needing a decision |
| `separator` | purple | Detected document breaks |

Shades are `base`, `hover`, `press`, `soft`, `soft_fg`, `soft_line`. The `soft`
trio is the tinted-background treatment used by pills and cards; `base` is for
solid fills. Use an alias (`theme.family("danger")`) unless you genuinely mean
the hue.

## Type

Three roles: `DISPLAY` for page titles, `SANS` for everything, `MONO` for
micro-labels and any value the user might compare digit by digit — ink
density, barcode payloads, keyboard shortcuts. Monospace micro-labels are
uppercase with wide letter-spacing; they are labels, so they stay short.

## Page states

The state vocabulary is shared by the batch table, the triage cards and the
summary, and it is the single most important thing to keep consistent:

| State | Colour | Eyebrow | Pill |
| --- | --- | --- | --- |
| Content page, kept | neutral card, green mark | `CONTENT PAGE` | `Keep` |
| Blank detected | red, dashed thumbnail frame | `BLANK PAGE DETECTED` | `Blank` |
| Separator detected | purple, dashed thumbnail frame | `DOCUMENT BREAK DETECTED` | `Separator` |

Eyebrows are uppercase mono and state what was *detected*. Pills are sentence
case and state what will *happen*. Dashed borders mean "this page will not
appear in the output" — kept pages are never tinted, so a clean batch looks
calm and the exceptions are the only thing with colour on the screen.

## Rules

These are load-bearing. Each one corresponds to a bug that shipped into a
screenshot at least once.

**Never bake a theme colour into an inline stylesheet at construction time.**
It survives `apply_theme()` and goes invisible in the other theme. Use a
stylesheet `variant` property, or re-apply the colour from `_restyle_chrome()`
when the theme changes.

**Scope every `setStyleSheet` to an object name.** A rule with no selector
applies to the widget *and all of its descendants*, so a card background will
also paint every label inside it. Write `QFrame#myCard { … }` and give the
widget a unique `objectName`.

**Solid fills cannot assume white text.** The neutral family inverts between
themes. Read `family()["fg"]` where it exists instead of hardcoding
`on_accent`.

**Pass an explicit rect to `QSvgRenderer.render()`.** Without one it renders
into the device viewport, which clips on any display where the device pixel
ratio is not 1 — that is most Windows laptops.

**Quote `url()` paths in stylesheets.** A frozen build unpacks under a temp
path that often contains a space; an unquoted URL stops parsing there and the
checkbox and combo glyphs silently vanish.

**Escape literal ampersands as `&&`** in button and label text, or Qt eats
them as accelerators.

**Compute layout in `showEvent`, not `__init__`.** A `QScrollArea` viewport has
no meaningful width until it is shown, so column maths done early always
yields one column. Guard on `usable <= 0`.

**Use `QSizePolicy.Policy.Preferred`, not `Ignored`,** for a label that should
shrink. `Ignored` collapses it to zero width.

## Adding a component

Put it in `ui/components.py`, build it from tokens only, and give it a test in
`tests/test_ui_design_system.py`. Check it in both themes — the fastest way is
to render it offscreen and actually look at the result:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_design_system.py
```

Adding an icon means dropping an SVG into `resources/icons/` — it is picked up
automatically, recoloured to the current foreground, and cached. Call
`icons.clear_cache()` if you change the theme outside `apply_theme()`.
