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
- PHY: tools/phy54.py (reader), tools/compare_phy54.py; layout in the format notes.
  `roundtrip54.py --render-only --with-physics` compares PHY as well as render data.
  Corpora: complex-native-s0/s1 (corrected VVC exports) and s2-raw/s3-raw. Keep only
  active corpora, the runtime and final reports in test-output; delete regenerated work.
  Corpus runs: `roundtrip54.py --discard-work` keeps only results.json (a full run is
  otherwise gigabytes); shard lists need LF line endings.
- BVH: tools/bvh54.py (reader), tools/compare_bvh54.py (run by roundtrip54 for every
  model with a BVH). In-game collision: tools/build_r5r_collision_test.py, then
  `ingame54.py --collision`. Lessons: R5R traces a SOLID_VPHYSICS prop_dynamic against
  its physics-hull entry and ignores props without a PHY (retail too); prop_physics
  needs prop_data or the game deletes it; drop physics props on level ground found by a
  search (slopes and terrain holes make them slide or fall away); trace declarations go
  at the top of the Squirrel file; close the test runtime's crashmsg.exe after a crash.
  More: TraceLineHighDetail reads the trace-mesh entry; TRACE_MASK_SHOT also hits
  hitboxes (use TRACE_MASK_SOLID to isolate collision); Squirrel limits a function's
  locals ("Too many locals"), so generated probes call helper functions; ragdolls are
  client-side (the server only sees its entity replaced) and need an ACT_DIERAGDOLL
  sequence; traces report the model's $surfaceprop, not the BVH surface table.
- GPL/AGPL references may be consulted, not copied into this MIT implementation.
- Run Python on extracted data with -I, with scripts outside the extraction folder.
- Packaging follows R1: package.ps1, check_package.ps1, tag-driven release.yml.
  Verify a fresh ZIP extraction. Update README, format notes and VALIDATION with
  actual executable hash and measured evidence. Parsing is not runtime proof.
