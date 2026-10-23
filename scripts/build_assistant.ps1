$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    python -m PyInstaller --noconfirm --clean --name ElectricityAssistant --distpath dist --workpath build --specpath build --collect-all mitmproxy_windows --collect-all mitmproxy_rs --collect-data mitmproxy --collect-submodules mitmproxy.addons assistant/assistant.py
    if($LASTEXITCODE -ne 0){throw 'Build failed'}
    Copy-Item -LiteralPath assistant/config.example.json -Destination dist/ElectricityAssistant/config.example.json
    & dist/ElectricityAssistant/ElectricityAssistant.exe --self-test
    if($LASTEXITCODE -ne 0){throw 'Packaged self-test failed'}
    & dist/ElectricityAssistant/ElectricityAssistant.exe --self-test-gui
    if($LASTEXITCODE -ne 0){throw 'Packaged GUI self-test failed'}
    Write-Output 'Users can enter their trusted website on first launch. Do not package runtime config or credentials.'
} finally {Pop-Location}
