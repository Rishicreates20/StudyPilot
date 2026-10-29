# Fonts embedded in exported PDFs

Downloaded on 2026-10-23 from the Noto project's official font distribution,
`https://raw.githubusercontent.com/notofonts/notofonts.github.io/main/fonts/<Family>/hinted/ttf/`.

| File | Covers |
|---|---|
| `NotoSans-Regular.ttf`, `NotoSans-Bold.ttf`, `NotoSans-Italic.ttf` | Latin (English), Greek, Cyrillic, common symbols |
| `NotoSansDevanagari-Regular.ttf`, `NotoSansDevanagari-Bold.ttf` | Devanagari (Hindi) |
| `NotoSansOriya-Regular.ttf`, `NotoSansOriya-Bold.ttf` | Odia |
| `NotoSansMono-Regular.ttf` | Code blocks |

All are licensed under the **SIL Open Font License 1.1** (`OFL.txt`), which allows bundling and
embedding them in documents. The licence text is identical across the three source repositories
apart from its copyright line:

- Copyright 2022 The Noto Project Authors (https://github.com/notofonts/latin-greek-cyrillic)
- Copyright 2022 The Noto Project Authors (https://github.com/notofonts/devanagari)
- Copyright 2022 The Noto Project Authors (https://github.com/notofonts/oriya)

PDFs embed only the glyphs they use (subsets). Devanagari and Odia are shaped with HarfBuzz
(`uharfbuzz`) through fpdf2's text shaping. Do not assume these fonts cover every script: the
exporter counts characters no font covers and reports them (`exports.unsupported_characters`).
