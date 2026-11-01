---
description: Build the Canlytics Windows .exe with PyInstaller (handles locked build folder)
allowed-tools: PowerShell
---

Compila el ejecutable onefile de Canlytics desde la raíz del repo usando el venv del proyecto.
El build puede tardar varios minutos — usa un timeout de al menos 600 000 ms.

## Argumento opcional

`$ARGUMENTS` (opcional) es una etiqueta de build (ej. `alpha`) para builds de prueba
que **no** deben tocar `config/version.py`. Si se pasa, el exe sale como
`Canlytics-X.Y.Z-<etiqueta>-win-x64.exe` en vez de `Canlytics-X.Y.Z-win-x64.exe`,
sin bumpear ni commitear ninguna versión. Vacío = build normal de release.

## Pasos

1. Mata cualquier proceso `Canlytics` en ejecución y elimina `localpycs` si existe:

```powershell
Stop-Process -Name "Canlytics" -Force -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "build\Canlytics\localpycs" -ErrorAction SilentlyContinue
```

2. Ejecuta el build (seteando `CANLYTICS_BUILD_SUFFIX` solo si se pasó `$ARGUMENTS`) desde la raíz del repo:

```powershell
$env:CANLYTICS_BUILD_SUFFIX = "<ARGUMENTS o vacío>"
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --distpath "dist" --workpath "build" Canlytics.spec 2>&1 | Select-Object -Last 5
Remove-Item Env:\CANLYTICS_BUILD_SUFFIX -ErrorAction SilentlyContinue
```

3. Lee la versión y verifica el output:

```powershell
$ver = (Select-String 'APP_VERSION\s*=\s*"(.+)"' "config\version.py").Matches[0].Groups[1].Value
$label = "<ARGUMENTS o vacío>"
$nameVersion = if ($label) { "$ver-$label" } else { $ver }
$exe = "dist\Canlytics-$nameVersion-win-x64.exe"
if (Test-Path $exe) {
    $mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host "OK  $exe  ($mb MB)"
} else {
    Write-Host "FAIL  not found: $exe"
}
```

Al terminar reporta:
- ✓ **Build OK** — ruta y tamaño del exe.
- ✗ **Build FAILED** — las últimas 30 líneas del error.

No hagas nada más — solo reporta el resultado. Nunca toques `config/version.py` ni
hagas commits/tags como parte de este comando (eso es trabajo de `/release`).
