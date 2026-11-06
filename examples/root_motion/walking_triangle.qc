$modelname "r5c_examples/walking_triangle.rmdl"
$origin 0 0 0 -90
$cdmaterials ""
$legacymovement
$body body "body.smd"
$ikchain leg foot links hip knee foot knee 1 0 0 angle_unknown 0.8660254
$sequence idle "body.smd" noautoik
$sequence walk {
    "stride.smd" fps 20 noautoik
    walkframe 20 LX LY LZR
    walkframe 40 LX LY LZR
    eventcycle "AE_R5C_MARKER" 0.375 "motion marker"
}
