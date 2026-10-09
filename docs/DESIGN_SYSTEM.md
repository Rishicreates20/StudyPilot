# Design system

A calm, focused interface for sustained reading and practice: warm neutral surfaces, one restrained
indigo accent, serif headings for a reading feel, and generous touch targets. It is built on
[shadcn/ui](https://ui.shadcn.com) (Radix primitives, copied into the repo and owned by us) with
Tailwind CSS v4.

**Live preview:** run the web app and open `/design`. Every value on that page is sample content for
design review; nothing is read from a database.

## Principles

1. **Tokens, not literals.** Components use semantic colour classes (`bg-card`, `text-muted-foreground`,
   `border-input`). Never hard-code a hex or `oklch()` value in a component.
2. **Accessible by construction.** Contrast, focus, target size and motion are properties of the
   system, and the contrast ratios are enforced by tests (see below).
3. **Every state exists.** Loading, empty, error and success states are components, not afterthoughts.
4. **Honest content.** No placeholder statistics presented as real data.
5. **Reading first.** Long-form content uses the serif heading face and comfortable measure.

## Tokens

Defined once in [`apps/web/src/app/globals.css`](../apps/web/src/app/globals.css) as OKLCH CSS variables
(light under `:root`, dark under `.dark`) and mapped to Tailwind colours.

| Token | Intent |
|---|---|
| `background` / `foreground` | Page surface and body text |
| `card` / `card-foreground`, `popover` / `popover-foreground` | Raised surfaces |
| `primary` / `primary-foreground` | The single accent: main actions, links, progress |
| `secondary`, `accent`, `muted` (+ `-foreground`) | Quiet surfaces, hover states, supporting text |
| `border` | Subtle dividers (decorative) |
| `input` | **Form-control outline**, deliberately stronger than `border` to reach 3:1 |
| `ring` | Keyboard focus indicator |
| `destructive`, `success`, `warning`, `info` | Status colours, each as a triplet: solid, `-soft` surface, `-foreground` text |

Radius is driven by one variable (`--radius`, 0.75rem). Spacing and type scale use Tailwind defaults.

### Typography

| Role | Face | Variable |
|---|---|---|
| Interface and body | Inter | `--font-inter` |
| Headings and reading | Source Serif 4 | `--font-source-serif` (`font-heading`) |
| Code | Geist Mono | `--font-geist-mono` |
| Hindi / Odia fallbacks | Noto Sans Devanagari, Noto Sans Oriya | `--font-devanagari`, `--font-oriya` |

The Indic faces are split by unicode-range, so the browser downloads them only when a page contains
those scripts (verified in the browser's font API).

## Accessibility rules that are enforced

- **Contrast** — [`design-tokens.test.ts`](../apps/web/src/test/design-tokens.test.ts) parses the real
  CSS and asserts WCAG 2.2 ratios in **both themes**: 4.5:1 for text pairs, 3:1 for form-control
  outlines and focus rings. Change a colour and the test re-checks it.
- **Focus** — buttons, inputs, badges-as-links and navigation links show a 2px ring with an offset on
  `:focus-visible`; menu items use a highlighted state; a global outline covers anything else.
- **Target size** — default controls are 40px high (large 44px), above the 24px WCAG 2.2 minimum.
- **Motion** — `prefers-reduced-motion` collapses all animation and transition durations; spinners and
  skeletons also carry `motion-reduce:` classes.
- **Announcements** — informational alerts use `role="status"`; warnings and errors use `role="alert"`.
  Loading regions announce once (`role="status"`), with decorative skeletons hidden from assistive tech.
- **Forms** — inputs always have a visible label and an `aria-describedby` hint or error.
- **Skip link** and landmark structure (`header`, `nav`, `main#main-content`, `footer`) on every page.

## Components

| Group | Components | Notes |
|---|---|---|
| Primitives (`components/ui`) | `Button`, `Input`, `Label`, `Card`, `Dialog`, `Sheet`, `DropdownMenu`, `Alert`, `Badge`, `Progress`, `Skeleton`, `Separator` | shadcn sources, adapted to the tokens |
| Button | variants `default`, `secondary`, `outline`, `ghost`, `destructive`, `link`; sizes `xs`…`lg`, icon sizes | `loading` shows a spinner, sets `aria-busy`, blocks clicks. Defaults to `type="button"` so it never submits a form by accident. `asChild` renders a link with button styling |
| Alert | variants `default`, `info`, `success`, `warning`, `destructive` | Role follows severity |
| Badge | adds `info`, `success`, `warning`, `destructive` | Used for status |
| Navigation (`components/layout`) | `SiteHeader`, `NavLinks`, `MobileNav`, `ThemeToggle`, `SiteFooter`, `SkipLink`, `PageContainer`, `PageHeader` | Desktop nav collapses into a drawer below `md`; current page gets `aria-current="page"`; theme menu offers Light / Dark / System |
| Feedback (`components/feedback`) | `EmptyState`, `LoadingState`, `CardGridSkeleton`, `ErrorState` | `ErrorState` supports a retry action and a support reference |
| Progress (`components/progress`) | `ProgressBar`, `ProgressRing` | Both are named `progressbar`s with clamped values |
| Status (`components/status`) | `ServiceStatusCard`, `RefreshButton` | Used by `/status` |

## Adding or changing a component

1. `npx shadcn@latest add <component>` from `apps/web` (components land in `src/components/ui`).
2. Replace any literal sizes/colours with tokens; use 40px+ targets and the standard focus ring.
3. Add it to `/design` and write a test for its behaviour and accessibility contract.
4. Run `npm run check`.

Note: the shadcn CLI used here generates `import { cn } from "cn"` — the `cn` package published by the
shadcn maintainers as a drop-in for `clsx` + `tailwind-merge` (maintainer and repository verified on npm).
