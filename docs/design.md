# Frontend Design Spec — Eliza.com Style

Observed from eliza.com: light enterprise aesthetic, white/off-white backgrounds,
pink-to-magenta gradient accent, dark charcoal text, geometric sans-serif typography,
flat minimal components with generous whitespace.

---

## Color Palette

### Backgrounds
| Role | Hex | Tailwind |
|---|---|---|
| Page background | `#FFFFFF` | `bg-white` |
| Section / card surface | `#F7F7F8` | `bg-gray-50` |
| Subtle divider / hover | `#F0F0F2` | `bg-gray-100` |
| Input background | `#FFFFFF` | `bg-white` |

### Text
| Role | Hex | Tailwind |
|---|---|---|
| Primary text | `#111118` | `text-gray-950` |
| Secondary text | `#6B7280` | `text-gray-500` |
| Muted / metadata | `#9CA3AF` | `text-gray-400` |
| Placeholder | `#D1D5DB` | `text-gray-300` |

### Accent — Pink/Magenta Gradient
Eliza's brand uses a warm pink-to-magenta gradient for hero imagery and emphasis.
Applied as solid or gradient depending on context.

| Role | Hex | Tailwind |
|---|---|---|
| Accent primary | `#E8197D` | `text-pink-600` |
| Accent hover | `#C4166A` | `text-pink-700` |
| Gradient start | `#F43F8E` | `from-pink-500` |
| Gradient end | `#A855F7` | `to-purple-500` |
| Accent background (chips) | `#FDF2F8` | `bg-pink-50` |
| Accent border | `#FBCFE8` | `border-pink-200` |

### Borders & Dividers
| Role | Hex | Tailwind |
|---|---|---|
| Default border | `#E5E7EB` | `border-gray-200` |
| Subtle divider | `#F3F4F6` | `border-gray-100` |
| Focus ring | `#E8197D` | `ring-pink-600` |

---

## Typography

**Font:** `Inter` (already loaded) — matches Eliza's geometric sans-serif
**Fallback:** `system-ui, sans-serif`

| Element | Size | Weight | Color |
|---|---|---|---|
| Page title / H1 | `text-2xl` | `font-semibold` | `text-gray-950` |
| Section heading | `text-xs uppercase tracking-widest` | `font-semibold` | `text-gray-400` |
| Body / answer text | `text-[15px]` leading-relaxed | `font-normal` | `text-gray-800` |
| Metadata / filing info | `text-xs` | `font-normal` | `text-gray-500` |
| Button | `text-sm` | `font-medium` | — |
| Snippet / code | `text-sm font-mono` | — | `text-gray-600` |

---

## Component Styles

### Header
```
bg-white border-b border-gray-100 sticky top-0 z-10
```
- Logo: brand name in `font-semibold text-gray-950`
- Subtle shadow: `shadow-sm`
- Accent dot or gradient mark next to logo

### Query Input
```
bg-white border border-gray-200 rounded-xl
focus-within:border-pink-400 focus-within:ring-1 focus-within:ring-pink-400
shadow-sm
```
- Textarea: `text-gray-900 placeholder-gray-300`
- Submit button: pink gradient bg with white text (see Button)

### Button — Primary
```
bg-gradient-to-r from-pink-500 to-purple-500
hover:from-pink-600 hover:to-purple-600
text-white font-medium rounded-lg px-4 py-2
transition-all shadow-sm
disabled:opacity-40 disabled:cursor-not-allowed
```

### Example Question Pills
```
text-xs text-gray-500 border border-gray-200
hover:border-pink-300 hover:text-pink-600 hover:bg-pink-50
rounded-full px-3 py-1.5 transition-colors bg-white
```

### Citation Chip `[n]`
```
/* default */
bg-pink-50 text-pink-600 border border-pink-200 rounded

/* active / clicked */
bg-pink-600 text-white border-transparent
```

### Source Card
```
/* default */
bg-white border border-gray-200 rounded-xl shadow-sm
hover:border-gray-300 hover:shadow-md transition-all

/* highlighted (citation clicked) */
border-pink-400 shadow-md shadow-pink-100/50 ring-1 ring-pink-300
```

### Ticker Badge
```
/* base */
bg-gray-100 text-gray-700 text-xs font-semibold px-2 py-0.5 rounded

/* sector overrides */
tech:     bg-blue-50   text-blue-700
pharma:   bg-emerald-50 text-emerald-700
finance:  bg-amber-50  text-amber-700
energy:   bg-orange-50 text-orange-700
auto:     bg-red-50    text-red-700
```

### Model Picker Dropdown
```
bg-white border border-gray-200 text-gray-700 text-sm rounded-lg
focus:ring-1 focus:ring-pink-400 focus:border-pink-400
```

### Answer Section Divider
```
border-t border-gray-100
```

### Empty State Icon
```
text-gray-300
```

### Error Banner
```
bg-red-50 border border-red-200 text-red-600 rounded-lg
```

### Loading Skeleton
```
bg-gray-100 animate-pulse rounded
```

---

## Gradient Accent Usage

Eliza uses pink-to-purple gradients sparingly for emphasis — hero imagery, 
section highlights, and branded moments. Apply in our UI:

1. **Submit button** — full gradient bg
2. **Active citation chip** — solid `bg-pink-600`
3. **Header logo mark** — small gradient square/dot
4. **Highlighted source card border** — `border-pink-400`
5. **Focus rings** — `ring-pink-400`

Avoid using the gradient on large background areas — keep it as an accent only.

---

## Spacing & Layout

- Max content width: `max-w-3xl mx-auto` (unchanged)
- Page padding: `px-4 py-8` (unchanged)
- Section gaps: `gap-8` (unchanged)
- Card internal padding: `px-4 py-3` (unchanged)
- Between source cards: `gap-2` → `gap-3` (slightly more breathing room)

---

## Summary of Changes vs. Current Dark Theme

| Element | Current (dark) | New (Eliza-style) |
|---|---|---|
| Page bg | `bg-slate-950` | `bg-white` |
| Card bg | `bg-slate-900` | `bg-white` |
| Border | `border-slate-800` | `border-gray-200` |
| Primary text | `text-slate-100` | `text-gray-950` |
| Secondary text | `text-slate-400` | `text-gray-500` |
| Accent color | `blue-600` | `pink-500 → purple-500` gradient |
| Button | `bg-blue-600` | `bg-gradient-to-r from-pink-500 to-purple-500` |
| Citation chip | `bg-slate-700` | `bg-pink-50 text-pink-600 border-pink-200` |
| Active chip | `bg-blue-500` | `bg-pink-600 text-white` |
| Source card highlight | `ring-blue-500` | `border-pink-400 ring-pink-300` |
| Input border | `border-slate-700` | `border-gray-200` |
| Input focus | `border-blue-500` | `border-pink-400 ring-pink-400` |
| Scrollbar | dark | `bg-gray-100 / bg-gray-300` |
| Section headings | `text-slate-500` | `text-gray-400` |
| Skeleton | `bg-slate-800` | `bg-gray-100` |
| Error banner | `bg-red-950 border-red-800` | `bg-red-50 border-red-200 text-red-600` |
