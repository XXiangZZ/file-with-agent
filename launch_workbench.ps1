$ErrorActionPreference = 'Stop'
# Compatibility with the project's existing Paddle 2.6.2 runtime.
if (-not $env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION) {
    $env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION = 'python'
}
# Reuse an adjacent distribution's complete local weights when available.
if (-not $env:ARCHIVE_OCR_MODEL_DIR) {
    $bundledModels = Join-Path (Split-Path $PSScriptRoot -Parent) '_internal\models\paddleocr'
    if (Test-Path -LiteralPath $bundledModels) {
        $env:ARCHIVE_OCR_MODEL_DIR = $bundledModels
    }
}
Push-Location (Join-Path $PSScriptRoot 'archive_tool')
try {
    python main.py
} finally {
    Pop-Location
}
