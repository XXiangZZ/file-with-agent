param(
    [string]$IncludeModules = "",
    [string]$BuildName = "archive_tool",
    [switch]$OneDir
)
$ErrorActionPreference = 'Stop'
# 打包全程终端内容同时写入 build_debug.log（含所有 Write-Host、PyInstaller 输出、错误警告），
# 便于出问题时排查构建过程。运行期 exe 的 stdout/stderr 重定向到同目录下的 debug.log（main.py 已实现）
$BuildLogFile = Join-Path (Get-Location) 'build_debug.log'
"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ======== PyInstaller 打包启动 ========" | Out-File -FilePath $BuildLogFile -Encoding utf8 -Append
Start-Transcript -Path $BuildLogFile -Append -ErrorAction SilentlyContinue
# 参数：按需包含的模块（逗号分隔），以及输出可执行文件名
# 可选：-OneDir 使用 dist/<BuildName>/ 目录式构建，否则默认生成单文件 exe
$cwd = Get-Location
Write-Host "Packaging project in $cwd"

$dirs = @('models','resources','config/templates','ui','build')
$add = @()
foreach ($d in $dirs) {
    if (Test-Path $d) {
        $add += '--add-data'
        $add += "$d;$d"
    }
}

$pythonExe = Join-Path $cwd '.venv\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) {
    $pythonExe = 'python'
}

# 如果存在 Cython 的 Utility 目录（包含 CppSupport.cpp），把它一并打包为数据文件
try {
    $cython_site = & $pythonExe -c "import site, sysconfig; p = site.getsitepackages()[0] if hasattr(site, 'getsitepackages') else sysconfig.get_paths().get('purelib'); print(p)"
    if ($cython_site) {
        $cython_util = Join-Path $cython_site 'Cython\Utility'
        if (Test-Path $cython_util) {
            Write-Host "Including Cython Utility files from: $cython_util"
            $add += '--add-data'
            $add += "$cython_util;Cython\Utility"
        }
    }
} catch {
    # 不影响主流程
}

# 另外优先检查项目虚拟环境下的 Cython Utility（常见位置）
$venv_cython_util = Join-Path $cwd ".venv\Lib\site-packages\Cython\Utility"
if (Test-Path $venv_cython_util) {
    Write-Host "Including venv Cython Utility files from: $venv_cython_util"
    $add += '--add-data'
    $add += "$venv_cython_util;Cython\Utility"
}

Write-Host "Installing pyinstaller (if needed)..."
& $pythonExe -m pip install -U pyinstaller

# 可排除的大体积可选依赖（根据项目情况调整）
$excludes = @('torch','tensorflow','transformers','onnx','onnxruntime','torchvision','torchaudio')

# 处理按需包含参数：如果用户指定了要包含的模块，则从排除列表中移除它们
if ($IncludeModules -ne "") {
    $includeList = $IncludeModules -split ',' | ForEach-Object { $_.Trim().ToLowerInvariant() } | Where-Object { $_ -ne '' }
    if ($includeList.Count -gt 0) {
        Write-Host "Requested include modules: $($includeList -join ', ')"
        if ($includeList -contains 'all') {
            $excludes = @()
        } else {
            foreach ($inc in $includeList) {
                $excludes = $excludes | Where-Object { $_ -ne $inc }
            }
        }
    }
}

$excludeArgs = @()
foreach ($e in $excludes) {
    $excludeArgs += "--exclude-module=$e"
}

# PaddleOCR runtime relies on package data and dynamic imports under paddleocr.tools.
# Collect all paddleocr submodules and package data to ensure frozen app can load them.
# Also include imageio/imgaug metadata because imgaug uses importlib.metadata to discover imageio.
$collectArgs = @(
    '--collect-all=paddleocr',
    '--collect-all=paddle',
    '--collect-all=imgaug',
    '--collect-all=imageio',
    '--collect-submodules=ppocr',
    '--collect-submodules=ppstructure',
    '--collect-submodules=tools'
)

$metadataArgs = @(
    '--copy-metadata=langchain-core',
    '--copy-metadata=langchain-text-splitters',
    '--copy-metadata=imageio',
    '--copy-metadata=imgaug'
)

$hiddenArgs = @(
    '--hidden-import=paddleocr.paddleocr',
    '--hidden-import=paddle',
    '--hidden-import=tools',
    '--hidden-import=tools.program',
    '--hidden-import=tools.naive_sync_bn',
    '--hidden-import=imgaug',
    '--hidden-import=imageio'
)

$pathArgs = @(
    '-p',
    (Join-Path $cwd '.venv\Lib\site-packages')
)
$hookPathArgs = @(
    '--additional-hooks-dir',
    (Join-Path $cwd 'build\pyinstaller-hooks')
)

$paddleLibs = Join-Path $cwd '.venv\Lib\site-packages\paddle\libs'
$binaryArgs = @()
if (Test-Path $paddleLibs) {
    Write-Host "Including paddle libs from: $paddleLibs"
    $binaryArgs += '--add-binary'
    $binaryArgs += "$paddleLibs;paddle/libs"
}

$addArgs = $add
$excludeArgs = $excludeArgs
$collectArgs = $collectArgs
$hiddenArgs = $hiddenArgs
$buildMode = if ($OneDir) { '--onedir' } else { '--onefile' }
$pyInstallerArgs = @('--clean', '--noconfirm', '--windowed', $buildMode, '--name', $BuildName) + $addArgs + $collectArgs + $metadataArgs + $binaryArgs + $hiddenArgs + $excludeArgs + $pathArgs + $hookPathArgs + @('main.py')

Write-Host "Running: $pythonExe -m PyInstaller $($pyInstallerArgs -join ' ')"
& $pythonExe -m PyInstaller @pyInstallerArgs

if ($OneDir) {
    if (Test-Path ".\dist\$BuildName\") {
        Write-Host "Build succeeded: .\dist\$BuildName\"
    } else {
        Write-Host "Build finished. Check .\dist\ folder for artifacts and logs (build/pyinstaller*.log)."
    }
} else {
    if (Test-Path ".\dist\$BuildName.exe") {
        Write-Host "Build succeeded: .\dist\$BuildName.exe"
    } else {
        Write-Host "Build finished. Check .\dist\ folder for artifacts and logs (build/pyinstaller*.log)."
    }
}
"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ======== PyInstaller 打包结束 ========" | Out-File -FilePath $BuildLogFile -Encoding utf8 -Append
Stop-Transcript -ErrorAction SilentlyContinue
