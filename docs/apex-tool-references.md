# Apex model-tool reference review

Reviewed 17 November 2026. These are source/README observations, not independent
runtime validation of the tools. Checkouts stay under ignored
`test-output/references`; no third-party implementation was copied into the compiler.

## Reviewed revisions and relevance

- [StudioRMDL](https://github.com/WateryContinent/studiormdl),
  `c8eb4be594cb209dbeccc5baa1d5db65272de26b` (GPL-3.0): targets S3 model v10;
  documents RUI import/dump, RMDL/VG/PHY output and external animations. Its
  `src/studiomdl/animconv_wrapper.cpp` calls the bundled animation converter's
  v49/v53 parsing and rig/sequence writers. Useful for interoperability fixtures
  and command conventions; its advertised standard QC support does not establish
  equivalent native semantics for every command.
- [RMDLEdit](https://github.com/WateryContinent/rmdledit),
  `fbd6f752a13f5d9e542779334a4c328cd05d2d64` (MIT): S3/v10 editor and previewer.
  `src/RMDLFile.cs` separately parses body parts/models and RUI headers/meshes.
  Its material-type pointer at 204 (0xCC), body-part fields at 236/240
  (0xEC/0xF0) and RUI fields at 300/304 (0x12C/0x130) agree with our existing
  early-profile reader. Useful as a second inspection view; preview success is
  not evidence of correct in-game rig or material behavior.
- [CafeFPS/rmdlconv](https://github.com/CafeFPS/rmdlconv),
  `db9677f453512fa0f44b363d0869a6bbf11b9417` (GPL-3.0): model conversion into S3/v10,
  including later input revisions. The README explicitly excludes animation
  conversion and warns of in-game issues. Its revision table is a research index,
  not sufficient evidence for adding later-season compiler profiles. In particular,
  season numbers and model subversions are not interchangeable.
- [R5-AnimConv](https://github.com/someoneatemylastsliceofpizza/R5-AnimConv),
  `6d2ff73da25dc23cab3e458b80f36493689fc68b` (GPL-3.0): documents v49/v53 MDL input,
  S7-28 sequence input, S3 output and experimental S21 output. Its sequence writer
  has paths for GUID-based autolayers, IK rules and frame movement. These are leads
  for unsupported dependency/IK work, not a reason to enable those features without
  matching-season binary surveys and runtime checks. Compression defaults and its
  event-skipping option must not become weaker compiler validation limits.
- [R5-AnimInspector](https://github.com/someoneatemylastsliceofpizza/R5-AnimInspector),
  `26b1777b967621f7073830cc8c2d9d3185eed633` (GPL-3.0): QC generation from RMDL,
  RRIG and RSEQ; README lists S3 and S9-27. `src/mdl/qc.cpp` walks each body-part
  model, preserves empty choices and resolves sequence autolayer GUIDs. This supports
  the direction of our body-group exporter and provides future external-dependency
  test ideas. Some source paths explicitly note untested behavior.

The WateryContinent projects link two additional SMD authoring tools:

- [BoneJig](https://github.com/WateryContinent/bonejig),
  `06c97d5ae188d5e590cf420c288bb90316d1cc23` (MIT): experimental Valve-to-Apex
  bone rerigging and QC generation. Despite its name, this is not a jiggle-bone
  runtime format reference.
- [QCForge](https://github.com/WateryContinent/qcforge),
  `b68da9b0688395def5c2bbb6e15bcedab20b5559` (MIT): experimental individual/batch
  SMD-to-QC generation. Useful for authoring workflow, not native binary proof.

## Consequences for this compiler

1. Preserve explicit season profiles. Later-version conversion support in another
   tool does not establish native write support here.
2. Keep body-part choices and empty models, and compare their structure. The v5
   corpus exposed 56 material-name differences with a `.vmt` suffix, rather than
   new body-choice or geometry differences. The exporter now preserves these exact
   names through source aliases and rename rules; comparisons remain exact. See
   VALIDATION.md for the measured follow-up run.
3. Record existing rig dependencies explicitly in RePak maps. `pack54.py` now accepts
   `--installed-animrig` for the already-tested Flatline fixture. It packages the
   authored rig and references the installed weapon rig; it does not import that
   rig, verify arbitrary skeleton compatibility or bundle game assets.
4. Investigate native asset-GUID layers and IK using owned sequence/rig samples,
   independently implement the required behavior, then test against retail in game.
   The existing unsupported-feature errors remain in place.
