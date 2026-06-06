# Report

This directory is a minimal, self-contained ACM LaTeX project. It uses the
double-column `sigconf` layout with the course-requested 11-point option. The
only files
retained from the upstream `acmart` distribution are:

- `acmart.cls`
- `ACM-Reference-Format.bst`

## Build

```bash
cd report
make
```

or:

```bash
cd report
latexmk -pdf main.tex
```

The result is `main.pdf`. Auxiliary LaTeX files are ignored. `main.pdf` is not
ignored so it can later be published or embedded by the static frontend.

Run `make clean` to remove auxiliary files while preserving the PDF, or
`make distclean` to remove the PDF too.

## Authoring

- `main.tex` contains metadata and section order.
- `sections/` contains report prose.
- `references.bib` contains cited sources.
- `figures/` and `tables/` contain selected publication artifacts copied or
  exported from `analysis/outputs/`.

The course asks for roughly four double-column pages and 2,500-3,000 words.
Use `docs/REPORT_BLUEPRINT.md` as the content checklist.
