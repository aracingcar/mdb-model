## Architecture & Code Style Rules
- Do not introduce new third-party libraries.
- Prefer flat, early-return logic over deep nesting.
- Do not add speculative interfaces or premature abstractions.
- After every file modification, run both existing test suites from the repository root:
  - Python: `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
  - JavaScript: `node --test tests/network-editor.test.cjs tests/runoff-editor.test.cjs tests/car.test.cjs`
- Report failed or unavailable checks explicitly; do not treat a partial test run as a pass. The repository currently has no `package.json`, and its Python tests use `unittest`; do not substitute `npm test` or `pytest` unless those runners are configured.
- `docs/engine.js` re-implements the Python model. When you change the model (`1_masking/`, `2a_rainfall_runoff/`, `3a_routing/`, `4_ecology/`, `5_outputs/`, `6_display/run_display.py`), make the matching change in `docs/engine.js` (and `docs/data/engine_*.json` if the data is affected) in the same change, and vice versa.
## Model robustness
- Check physical correctness independently of Python/browser parity: both implementations can agree on the same mistake. Changes to runoff, routing, splits or storage must add or update small regression tests accounting for inflows, outflows, losses and changes in storage, including any modelled exchanges and explicit numerical tolerances.
- State units at model boundaries and conversions (especially mm/day, km², m³/s and ML/day). Validate aligned daily dates, finite values and parameter bounds. Reject missing days, duplicate dates and invalid inputs; any filling, clipping or fallback must have a documented modelling reason and a test.
- For affected calculations, test relevant boundary conditions: dry periods, extreme rainfall, empty inputs, leap days, July–June water-year boundaries, network cycles and split fractions. Document initial storage and warm-up assumptions when comparing simulation periods; account for water still in storage at the end.
- When browser calculations change, bump `ENGINE_VERSION` in `6_display/template.html`. For any model, parameter or input change, identify which stored results, upstream link flows, caches and generated display bundles become stale; rebuild affected artifacts in dependency order or explicitly report what still needs rebuilding. Edit generator sources rather than only generated copies.
- Explain changes to scientific parameters, calibration, ecology thresholds or modelling assumptions, including their evidence and expected effect on results. Do not change tolerances, expected test values or calibration merely to make checks pass; justify intentional numerical changes independently.
## Git: committing and pushing
- You may commit and push without being asked.
- Before committing or pushing, run `git status` and `git diff` to check for changes made outside this chat (by the user or another session). Only stage the files you changed in this session; never include those other changes, and never use `git add -A` or `git add .`.
## Before pushing: browser-engine parity (quick version only)
`docs/engine.js` re-implements the Python model, and `6_display/engine_parity.py` checks the two agree. The full run takes ~16 minutes, so do not run it on a push. If you changed anything that can affect the engine in this session (files in `1_masking/`, `2a_rainfall_runoff/`, `3a_routing/`, `4_ecology/`, `5_outputs/`, `6_display/run_display.py`, `docs/engine.js`, or the engine data in `docs/data/engine_*.json`), run only the quick check from `6_display/` before you push, and fix any MISMATCH it reports:

    python engine_parity.py --changed --years 2027-2036

- It tests just the systems and methods your changes touch (against `origin/main`) over ten years, typically under a minute per system; it says "nothing to check" and passes when nothing relevant changed.
- If you did not touch any of those files in this session, skip it and push.
- Run the full check (`python engine_parity.py`) only if the user asks for it.
