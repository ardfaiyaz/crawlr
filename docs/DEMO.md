# Recording the demo GIF

A short GIF of Crawlr in action is the single best thing for adoption — put it
in the README and the website hero. The repo ships a ready-to-run recording
script using [VHS](https://github.com/charmbracelet/vhs) (deterministic, no
screen-capture needed).

## Steps

1. Install VHS: `brew install vhs` (macOS) or see the VHS releases page.
2. From the repo root, run:
   ```bash
   vhs docs/demo.tape
   ```
   This produces **`docs/demo.gif`**.
3. Reference it in `README.md`:
   ```markdown
   <p align="center"><img src="docs/demo.gif" alt="Crawlr demo" width="760"></p>
   ```
4. For the website hero, copy the GIF into `web/` and add an `<img>` in
   `web/index.html`.

## Alternatives

- **asciinema** — `asciinema rec demo.cast`, then convert with
  [`agg`](https://github.com/asciinema/agg): `agg demo.cast docs/demo.gif`.
- **terminalizer** — `terminalizer record demo` then `terminalizer render demo`.

Keep it under ~15 seconds and show the highest-value flow: `watch` → `watchlist`.
