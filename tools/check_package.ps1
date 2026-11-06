param([string]$Archive = (Join-Path $PSScriptRoot '..\dist\r5-model-compiler-win64.zip'))
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$work = Join-Path ([IO.Path]::GetTempPath()) ('r5c-package-' + [guid]::NewGuid().ToString('N'))
try {
    Expand-Archive -LiteralPath $Archive -DestinationPath $work
    $exe = Join-Path $work 'r5studiomdl.exe'
    $built = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'build\r5studiomdl.exe')).Hash
    if ((Get-FileHash -LiteralPath $exe).Hash -ne $built) { throw 'Packaged executable hash mismatch.' }
    $examples = @(Get-ChildItem -LiteralPath (Join-Path $work 'examples') -Recurse -Filter '*.qc')
    if ($examples.Count -ne 6) { throw 'Expected exactly six authored examples.' }
    foreach ($target in @('s0','s1','s2','s3')) {
        $models = @()
        foreach ($qc in $examples) {
            $model = Join-Path $work ("out\$target\" + $qc.BaseName + '.rmdl')
            & $exe --target $target -quiet -o $model $qc.FullName
            if ($LASTEXITCODE) { throw "Compiling $($qc.Name) for $target failed." }
            $models += $model
        }
        & python -I (Join-Path $work 'tools\roundtrip54.py') --target $target --compiler $exe --out (Join-Path $work "roundtrip\$target") @models
        if ($LASTEXITCODE) { throw "Packaged $target examples did not round-trip." }
    }
    foreach ($tool in @('pack54.py','ingame54.py')) {
        & python -I (Join-Path $work "tools\$tool") --help | Out-Null
        if ($LASTEXITCODE) { throw "Packaged $tool did not start." }
    }
    Write-Output 'Package check passed: six examples, four targets, 24 round trips.'
} finally {
    $resolvedWork = [IO.Path]::GetFullPath($work)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if (!$resolvedWork.StartsWith($tempRoot,[StringComparison]::OrdinalIgnoreCase) -or !(Split-Path $work -Leaf).StartsWith('r5c-package-')) { throw 'Unsafe cleanup path.' }
    if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force }
}
