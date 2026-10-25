## Repository instructions
(Shared with CLAUDE.md.)
## Architecture & Code Style Rules
- Do not introduce new third-party libraries.
- Prefer flat, early-return logic over deep nesting.
- Do not add speculative interfaces or premature abstractions.
- Run `npm test` (or `pytest`) after every file modification.
## Before pushing: browser-engine parity (quick version only)
`docs/engine.js` re-implements the Python model, and `6_display/engine_parity.py` checks the two agree. The full run takes ~16 minutes, so do not run it on a push. If you changed anything that can affect the engine in this session (files in `1_masking/`, `2_rainfall_runoff/`, `3_routing/`, `4_ecology/`, `5_outputs/`, `6_display/run_display.py`, `docs/engine.js`, or the engine data in `docs/data/engine_*.json`), run only the quick check from `6_display/` before you push, and fix any MISMATCH it reports:

    python engine_parity.py --changed --years 2027-2036

- It tests just the systems and methods your changes touch (against `origin/main`) over ten years, typically under a minute per system; it says "nothing to check" and passes when nothing relevant changed.
- If you did not touch any of those files in this session, skip it and push.
- Run the full check (`python engine_parity.py`) only if the user asks for it.
