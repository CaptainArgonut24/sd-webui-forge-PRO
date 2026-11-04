# Forge Companion: three packages

These are three separate deliverables with one shared Forge host:

1. **Forge Server** (`ForgeServer.exe`) runs the existing Forge installation on
   the Windows PC and hosts its UI for local and Wi-Fi clients.
2. **Windows Front End** (`ForgeCompanion.exe`) is a desktop window for
   connecting to Forge. It does not start or bundle the server.
3. **Android Front End** (`ForgeCompanion-debug.apk`) is a mobile app for
   connecting to that same server over Wi-Fi.

The front ends display Forge's existing Gradio interface. Generation,
extensions, settings, models, and output files stay on the Windows Forge
installation, so both clients use the same live server and data.

## 1. Forge Server for Windows

Forge, its Python environment, and model files must already be installed on
the host PC. Build the server launcher from the repository root:

```powershell
dotnet publish .\apps\ForgeServer\ForgeServer.csproj -c Release `
  -o .\apps\ForgeServer\artifacts
```

Copy `ForgeServer.exe` from that folder to the Forge PC. It uses the installed
Forge environment; **it does not bundle Stable Diffusion, Python, PyTorch, or
models into the executable**. Start the server:

```powershell
.\ForgeServer.exe --forge-dir "C:\path\to\sd-webui-forge-PRO"
```

The launcher binds the server for Wi-Fi access on port `7860` and keeps the
console open for server logs. Keep it open while using either front end. Use
`--port 7861` to choose another port. If no `--forge-dir` is supplied, it
searches the current directory and its parents for `webui.bat` and `launch.py`.
The first launch can take several minutes while Forge initializes.

Only allow access on a trusted private network. The server UI can be used by
other devices on that network; set up Forge authentication and Windows
Firewall restrictions as appropriate. Do not expose it directly to the
public internet.

## 2. Windows Front End

Build the desktop client:

```powershell
dotnet publish .\apps\ForgeCompanion\ForgeCompanion.csproj `
  -f net10.0-windows10.0.19041.0 -c Release `
  -p:WindowsPackageType=None -p:PublishSingleFile=false -p:SelfContained=false `
  -o .\apps\ForgeCompanion\artifacts\windows
Compress-Archive -Path .\apps\ForgeCompanion\artifacts\windows\* `
  -DestinationPath .\apps\ForgeCompanion\artifacts\ForgeCompanion-Windows.zip -Force
```

Extract the zip and run `ForgeCompanion.exe`. It opens the local server URL by
default; enter another server URL if needed. Install the .NET 10 Desktop and
Microsoft Edge WebView2 runtimes if they are not already present.

## 3. Android Front End

Build a debug APK:

```powershell
dotnet publish .\apps\ForgeCompanion\ForgeCompanion.csproj `
  -f net10.0-android -c Debug
```

Install `com.captainargonut24.forgecompanion-Signed.apk` from
`apps\ForgeCompanion\bin\Debug\net10.0-android\` on the phone. For release
distribution, configure your Android signing key and publish the Release
configuration.

Keep the phone and host PC on the same Wi-Fi network. In the app, enter the
PC's URL from Forge's **Settings > Network** (for example
`http://192.168.1.25:7860`) and tap **Connect**. The app remembers the URL.
Allow the server through Windows Firewall on private networks if prompted.

## Project roles

- `apps/ForgeServer/` builds the Windows host launcher.
- `apps/ForgeCompanion/` builds the Windows and Android front ends.
- `webui.bat`, `launch.py`, Forge's Python environment, models, and data remain
  the actual server installation and are not included in either client package.
