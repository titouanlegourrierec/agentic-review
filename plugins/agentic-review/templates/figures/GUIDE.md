# Figures of the reading edition

The figures of a review live in `5-final/figures/`: one `figures.json` that lists them, plus one `.svg` file per
diagram. `ar-edition` draws the charts, checks every figure and places it in the page. `ar-figures check <dir>` runs
the same checks without building the page; `ar-figures preview <dir> --png` draws each figure alone, in both themes,
so that you can look at it.

Start from the examples: `examples/figures.json` holds the six figures of the original k-space review (a forest plot,
a taxonomy diagram, a family-by-year grid, a bar chart of rigor markers, a rigor heatmap, a dumbbell of headline
against stricter gains) and two more (a scatter, stacked columns); `examples/templates.json` holds a pipeline diagram
and a custom slope chart (`slope.svg`). `ar-figures gallery --png` draws them all.
Copy the entry closest to what you need, then change its data and words.

## What makes a good figure here

- **One question per figure**, one the review raises and a table or a sentence answers less well: where the
  evidence sits on one scale, how a pattern spreads across papers, how families relate.
- **Only the review's numbers.** A chart shows what the review, `counts.json` or a paper's record already states;
  the figure adds no finding. Prefer the review's own tables (`Methodology comparison`, `Methodological rigor`)
  and counts that the script computes from the records.
- **The caption gives the message and the denominator**: what is plotted, n, where the numbers come from (which
  section, which set of papers), and the one thing to see. Captions of computed figures must say which papers
  were counted (for example "all 62 catalogued papers" or "the 42 core papers").
- **Three to six figures** for a full review, one or two for a mini review. A taxonomy diagram almost always
  earns its place; a chart that repeats a three-row table does not.

## The file

```json
{
  "figures": [
    {
      "id": "rigor-scores",
      "type": "heatmap",
      "title": "Rigor scores of the six appraised papers",
      "caption": "Eight criteria scored 0 to 2 ... [Methodological rigor](#Methodological rigor).",
      "place": {"section": "Methodological rigor", "after": "paragraph"},
      "source": {"section": "Methodological rigor"},
      "mention": "Figure {n} shows every score.",
      "from": "rigor_scores"
    }
  ]
}
```

- `id`: lowercase letters, digits and hyphens; the page anchor is `#fig-<id>`.
- `type`: `dots`, `bars`, `columns`, `scatter`, `heatmap`, `diagram` or `custom`, and the fields of that type
  (below). Use a chart type when one fits; `custom` is for a chart none of them can draw.
- `title` (bold, one line) and `caption` (what is plotted, n, the source, the one thing to see).
- `place.section`: a heading of `review.md` (`##`, `###` or `####`), as written there.
- `place.after`: `"paragraph"` (the first paragraph under the heading, the default), `"heading"`, `"table"` (the
  first table of the section), or the first words of a paragraph of that section.
- `source.section` (and `source.subsection`): where the plotted numbers are discussed, when that is not where the
  figure goes. Links on rows open the passage that supports that section (Zotero) and its words guide the choice.
- `mention` (optional): a sentence appended to the paragraph the figure follows; `{n}` becomes "Figure 3" as a link.
  It needs `after` to be a paragraph: a figure placed after a heading or a table has no mention.
- In a caption, `[text](#Heading)` links to a heading of the review and `{fig:<id>}` to another figure.
- `key` on a row, point or `<a>` names a paper of `citation_map.tsv`. Its label comes from the map; the row then
  opens the paper (the highlighted passage with Zotero, the publisher's page without) and previews it on hover.
  Rows without a key need a `label`.

Every number in a figure (values, captions, labels, notes) must appear in `review.md`, `counts.json`, or the
record, rigor scores or claim checks of the paper on that row; numbers the script computes are allowed too. A
figure that breaks this, names an unknown key or heading, or has an unknown field value is refused, and
`ar-edition` writes nothing until it is fixed or removed.

## Chart types

Charts are drawn by the script: you give data, never coordinates or colours. Colours are slots `1` to `8`
(blue, orange, aqua, yellow, magenta, green, violet, red, in that order), or `"muted"` and `"ink"`. Use slot 1
for the main series, and keep a hue to one meaning across figures.

### dots: values of each row on one axis

Forest plots, ranges, before-and-after pairs (dumbbells). Signed values are fine.

```json
"axis": {"min": -3.3, "max": 2.7, "ticks": [-3, -2, -1, 0, 1, 2], "signed": true, "unit": "dB",
         "label": "Change in PSNR (dB)", "left": "← worse", "right": "better →"},
"series": [{"id": "core", "label": "core comparison", "marker": "filled", "colour": 1},
           {"id": "edge", "label": "edge case", "marker": "hollow", "colour": 1}],
"groups": [{"id": "core", "label": "Core comparisons"}, {"id": "edge", "label": "Edge cases"}],
"band": {"from": -1.2, "to": 0.7, "label": "−1.2 to +0.7 dB", "group": "core", "legend": "core range"},
"rows": [{"key": "souza2020dual", "sub": "what is compared", "group": "core",
          "values": {"core": [0.7, 0.6]}, "text": "+0.7 / +0.6 dB at R = 4 / 8", "note": "caveat"}]
```

**One measure per axis.** Every point of a chart is in the axis's unit (dB PSNR, say). A row whose result is in
another measure (SSIM, SER, a reader score) gets no point: give its result in `text`. Never mark the odd unit
with a different symbol on the same axis.

Markers: `filled`, `hollow`, `diamond`, `square`. Several values in one series draw a range; values in two series
are joined by a grey line (the dumbbell of `headline-vs-strict`). A row with no values shows only its text. At most
40 rows and 4 series.

### bars: one value per row

```json
"rows": [{"label": "Releases code", "value": 35, "of": 76},
         {"label": "k-space computed from magnitude images (a weakness)", "value": 34, "of": 76, "style": "weak"}],
"axis": {"label": "share of the 76 classified papers"}
```

With the same `of` on every row the axis is a percentage; `style: "weak"` hatches a bar that counts a weakness.
Counted from the records instead:

```json
"from": "records", "group": "family", "where": {"tier": "core"}, "share": true, "sort": "value"
```

### columns: counts along an ordered axis (usually years), optionally stacked

```json
"from": "records", "x": "year", "stack": "tier", "cited": true
```

or explicit: `"series": [{"id": "core", "label": "Core"}, ...]`, `"columns": [{"x": "2021", "values": {"core": 8}}]`.
More than eight stacks fold into "Other". Missing years between the first and last appear as empty columns.

### scatter: one point per paper on two measures

```json
"x": {"label": "Year of the version cited", "min": 2017, "max": 2026},
"y": {"label": "Rigor score (of 18)", "min": 0, "max": 18, "log": false},
"points": [{"key": "xu2025...", "x": 2025, "y": 15, "tag": true}]
```

`tag: true` prints the paper's label beside the point (tag a few, never all). At most three series. Two measures
of different units are two charts, never one chart with two y-axes. A scatter shows co-occurrence; its caption must
not claim a trend the review does not test.

### heatmap: rows by columns

From the rigor scores (rows are the scored papers, columns the rubric's criteria, a total bar and a mean row):

```json
"from": "rigor_scores", "sort": "total"
```

From the records (counts per cell, empty cells for zero):

```json
"from": "records", "rows": "family", "columns": "year", "where": {"tier": "core"}
```

Or explicit: `"columns": [{"id": "R1", "label": "Data"}]`, `"rows": [{"key": ..., "values": {"R1": 2, "R2": null},
"total": 9, "of": 16}]`, `"scale": {"min": 0, "max": 2}`, `"mean": true`, `"column_totals": true`. `null` is drawn
hatched ("not assessed").

Record fields you can count by: `tier` and `family` (after re-tiering; a paper counts under its first-listed
family), `year` (the year of the version cited), `venue_type`, `evidence_depth`, or any other record field.
`where` keeps records whose field equals a value or one of a list; `cited: true` keeps the papers the review cites.

## Diagrams

For ideas without data: a taxonomy, a method's pipeline, how families relate. Draw an SVG file (`viewBox="0 0 680
H"`) in `5-final/figures/` and list it with `"type": "diagram", "file": "taxonomy.svg"`. Start from
`examples/taxonomy.svg` (panels, boxes, arrows, a legend) or `examples/pipeline.svg` (a flow with a loop).

Rules (the check refuses the file otherwise):

- Elements: `g`, `rect`, `circle`, `ellipse`, `line`, `polyline`, `polygon`, `path`, `text`, `tspan`, `title`,
  `desc`, `a`. No `style`, `script`, `foreignObject`, `image`, `id`, `href`, event handlers or other namespaces.
- Colour only through classes, never `fill="#..."` or `stroke="#..."`, so both themes work:
  `fill-1` ... `fill-8` and `line-1` ... `line-8` (the series hues), `fill-ink`, `fill-ink2`, `fill-muted` (text and
  dark marks), `fill-panel`, `fill-grid`, `fill-surface`, `fill-wash`, `fill-axis`, `fill-q1` ... `fill-q5`
  (light to dark blue), `line-ink2`, `line-grid`, `line-axis`, `line-muted`, `line-surface`; text on a coloured
  box takes `on-dark`. `fill="none"` is allowed.
- Arrows: `marker-end="url(#fg-arrow)"` (or `#fg-arrow-muted`).
- Text: at least `font-size="8"`; the default is 9.5. Labels say what a box does in words of the review.
- Links: `<a data-section="F3 Sequential cascades">` jumps to a heading; `<a data-key="smith2021deep">` opens a
  paper. Numbers in text follow the number rule.

## Custom charts

For a chart the five types cannot draw (a slope chart, a timeline, small multiples, a Bland-Altman plot, a chart
with annotations in the plot), draw the SVG yourself, under the diagram rules above, and declare how values map to
coordinates. Compute every coordinate with a short script (in `.scripts/`) rather than by hand: start from
`examples/slope.svg`.

```json
{"id": "slope", "type": "custom", "file": "slope.svg", "title": "...", "caption": "...",
 "place": {"section": "..."}, "source": {"section": "..."},
 "axes": {"y": {"data": [0, 5], "px": [300, 60], "label": "PSNR gain (dB)"},
          "x": {"data": [2016, 2026], "px": [72, 660], "label": "Year", "log": false}}}
```

`data` gives two values and `px` the SVG coordinates where they are drawn (a y axis usually runs upwards, so its
second `px` is smaller). More panels take more axes: `x2`, `y2` ..., chosen on a mark or a group with
`data-xaxis="x2"` / `data-yaxis="y2"`: everything inside the group, marks and ticks, then uses that axis, so one
panel is one group. The data table under the figure gives each axis label its own column.

In the SVG, every element that shows a value says which value:

| Mark | Annotation | Checked |
|---|---|---|
| `circle`, `ellipse` | `data-x`, `data-y` | the centre |
| `rect` (a bar) | `data-y` (or `data-x`) and `data-base` | one edge at the value, the other at the base |
| `line` | `data-x1`, `data-x2`, `data-y1`, `data-y2`; or `data-x` / `data-y` for a reference line | the ends |
| `polyline` | `data-points="2016,3 2017,5 ..."` | every point |
| tick: `line` or centred `text` | `data-xtick="2"`, `data-ytick="2"` | its place; a label must read its value |

- Each mark must sit within 1 unit of where its value belongs, and each axis that marks use needs at least two
  ticks (a gridline or tick line, or a label). A misplaced mark, a tick in the wrong place or a label that reads
  another value is refused. Marks and ticks may sit in groups moved by `translate(...)`, never rotated or scaled.
- `data-key` on a mark or a group links it to the paper (hover preview, click to open) and lets its values come from
  that paper's record; `data-label` and `data-series` name it in the data table under the figure. Both are inherited
  by the marks inside a group.
- Values follow the number rule; tick values do not need to (they are the scale).
- A figure without any data mark is a `diagram`. Colours, elements and text follow the diagram rules.

## Looking at the result

`ar-figures preview <dir> --png` writes `5-final/figures/preview/<id>-light.png` and `-dark.png`. Read them and
check: no text overlaps or runs out of its box, labels fit, the legend matches the marks, the zero line and the
scale are right, the dark version is legible. The data table under each chart ("Data behind the figure") repeats
every value, so long labels shortened with … in the chart stay readable there.
