Forge client launchers
=====================

1. ForgeServer.exe
   Run this on the Windows PC that has Forge, its Python environment, and
   models installed. Keep the console window open while you use Forge.
   The launcher starts Forge on the local network.

2. windows.exe
   Run this to open the Forge front end in its own Windows app window. Keep
   all the ForgeCompanion runtime files and folders beside this executable.
   Enter the server PC URL shown in Forge Settings > Network, then click
   Connect. Example: http://192.168.1.25:7860
   The connection settings collapse to a compact server bar after connecting.
   Click "Change server" to reopen them.
   Windows also needs the .NET 10 Desktop Runtime and Microsoft Edge WebView2
   Runtime installed.

3. android.apk
   Install this on an Android device. Connect the phone and server PC to the
   same Wi-Fi network. Enter the URL shown in Forge Settings > Network.

Forge, Python/PyTorch, and the model files are installed only on the server PC.
The apps connect to that shared server; they do not contain the model runtime.
Allow the server through Windows Firewall on trusted private networks only.

See apps\ForgeCompanion\README.md in the repository for detailed setup and
build instructions.
