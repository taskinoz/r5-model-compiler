$modelname "r5c_examples/native_triangle.rmdl"
$origin 0 0 0 -90
$cdmaterials ""
$body body "body.smd"
$sequence idle "body.smd" noautoik
$sequence walk "stride.smd" fps 20 noautoik rm

$attachment "REF" "hip" 0 0 0
