# R5 compiler guide

Read README.md, VALIDATION.md and docs/mdl-v54-format.md before changing writers.

- Maintain the R1/R2 sibling pattern: r5studiomdl and native *54.py tools.
- Require an explicit season. S0/S1 use components; S2/S3 use VG1. Later seasons
  and retail require real profiles, not just a v54 integer or renamed executable.
- Build with build.bat, run CTest and locked uv unittest discovery. Add a native
  regression for each feature. Native tests: tests/test_compiler54.py.
- tests/legacy_v53, tools/legacy_v53 and docs/reference are inherited TF2 material,
  not native evidence. Root v53 helpers provide shared utilities only.
- Never loosen a threshold to make a model pass. Render-only passes do not prove
  metadata, collision, animation-rig or runtime equivalence.
- Fail explicitly for unsupported native features instead of emitting TF2 data.
- Reports identify compiler/tool hashes. Do not edit tools during corpus runs.
  Use build-dev.bat for experiments while build is in use.
- Game assets and research tools stay ignored under test-output. Do not distribute
  raw assets, modified extractors or game-derived output.
- Early installs: F:/Games/Apex Detours/Apex s0 through Apex s3. Retail: C:/Games/Apex.
  Do not modify or launch current retail. Coordinate shared runtime use with other
  agents before any future self-hosted game tests.
- GPL/AGPL references may be consulted, not copied into this MIT implementation.
- Run Python on extracted data with -I, with scripts outside the extraction folder.
- Packaging follows R1: package.ps1, check_package.ps1, tag-driven release.yml.
  Verify a fresh ZIP extraction. Update README, format notes and VALIDATION with
  actual executable hash and measured evidence. Parsing is not runtime proof.
