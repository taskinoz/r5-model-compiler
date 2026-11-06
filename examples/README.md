# Authored Apex examples

No game assets are included. Choose --target s0, s1, s2 or s3.

- static_prop/box.qc: static box without unsupported native collision.
- animated_prop/animated_prop.qc: three-bone prop with idle/bend and an attachment.
- lod_prop/lod_box.qc: explicit second LOD, reusing the box to expose LOD layout.

Compile with r5studiomdl --target s3 -o out/animated.rmdl
examples/animated_prop/animated_prop.qc. Outputs need a matching-season RPak packager
and materials for runtime use. No example is an in-game validation claim. The unused
inherited physics.smd is reference source and is not compiled.
