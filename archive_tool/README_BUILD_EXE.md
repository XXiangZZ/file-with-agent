# 打包为 EXE

运行以下步骤以在 Windows 上将项目打包为单文件 exe：

1. 激活项目虚拟环境（如果有）：

```powershell
& .\.venv\Scripts\Activate.ps1
```

2. 在项目根目录运行 PowerShell 脚本（会安装 PyInstaller 并执行打包）：

```powershell
.\build_exe.ps1
```

或使用批处理：

```cmd
build_exe.bat
```

生成文件位于 `dist\archive_tool.exe`（若成功）。注意：模型文件夹 (`models`) 与资源目录会被一起打包，最终可执行文件可能很大。

可选：脚本会默认排除一些大体积但通常为可选的深度学习库以加快打包：`torch`, `tensorflow`, `transformers`, `onnx`, `onnxruntime`, `torchvision`, `torchaudio`。
如果你的运行环境需要这些库，请在目标机器上单独安装，或使用 `-IncludeModules "all"` 将它们全部包含进构建；同时你也可以选择 `-OneDir` 目录式构建以避免单文件打包带来的路径问题。

按需打包示例：

- 仅打包默认（会排除上述库）：

```powershell
.\build_exe.ps1
```

- 若想在可执行文件中包含某些模块（例如 `onnx` 与 `onnxruntime`），传入 `-IncludeModules`：

```powershell
.\build_exe.ps1 -IncludeModules "onnx,onnxruntime"
```

- 若想包含所有默认排除项，传入 `all`：

```powershell
.\build_exe.ps1 -IncludeModules "all"
```

- 指定输出可执行名：

```powershell
.\build_exe.ps1 -IncludeModules "onnx" -BuildName "archive_with_onnx"
```

- 使用目录式构建（建议大型依赖包，输出 `dist\<BuildName>\`）：

```powershell
.\build_exe.ps1 -IncludeModules "all" -BuildName "archive_with_all" -OneDir
```

生成的构建位于 `dist\<BuildName>.exe` 或 `dist\<BuildName>\`，取决于是否使用 `-OneDir`。
