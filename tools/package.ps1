param([string]$OutputDirectory = (Join-Path $PSScriptRoot '..\dist'))
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$compiler = Join-Path $projectRoot 'build\r5studiomdl.exe'
if (!(Test-Path -LiteralPath $compiler)) { throw 'Run build.bat first.' }
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
$package = Join-Path $outputRoot 'r5-model-compiler'
# Validate the exact staging directory before removing an older package.
if ([IO.Path]::GetFullPath($package) -ne (Join-Path $outputRoot 'r5-model-compiler')) { throw 'Invalid staging path.' }
if (Test-Path -LiteralPath $package) { Remove-Item -LiteralPath $package -Recurse -Force }
New-Item -ItemType Directory -Path $package -Force | Out-Null
Copy-Item -LiteralPath $compiler -Destination $package
foreach ($name in @('README.md','LICENSE','VALIDATION.md')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $name) -Destination $package
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'examples') -Destination $package -Recurse
New-Item -ItemType Directory -Path (Join-Path $package 'docs'),(Join-Path $package 'tools') | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\mdl-v54-format.md') -Destination (Join-Path $package 'docs')
foreach ($tool in @('mdl54.py','decompile54.py','validate54.py','survey54.py','roundtrip54.py','pack54.py','ingame54.py',
                    'mdl53.py','decompile53.py','phy.py','phy54.py','compare_phy54.py')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "tools\$tool") -Destination (Join-Path $package 'tools')
}
$archive = Join-Path $outputRoot 'r5-model-compiler-win64.zip'
if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
Compress-Archive -Path (Join-Path $package '*') -DestinationPath $archive
$sums = foreach ($path in @($archive,$compiler)) {
    '{0}  {1}' -f (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower(),(Split-Path $path -Leaf)
}
[IO.File]::WriteAllText((Join-Path $outputRoot 'SHA256SUMS.txt'),($sums -join "`n")+"`n")
$sums
