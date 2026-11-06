$modelname "r5c_examples/animated_prop.rmdl"
$cdmaterials ""
$body "body" "body.smd"
$sequence "idle" "body.smd"
$sequence "bend" "bend.smd" fps 30 loop
$sequence "lean" {
    "body.smd" "bend.smd"
    blend "lean_amount" 0 1
    fadein 0.15 fadeout 0.25
    eventcycle "AE_R5C_MARKER" 0.375 "blend marker"
}
$attachment "probe" "head" 0 0 0
