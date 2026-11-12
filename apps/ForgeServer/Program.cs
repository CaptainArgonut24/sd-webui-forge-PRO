using System.Diagnostics;

namespace ForgeServer;

internal static class Program
{
    private const int DefaultPort = 7860;

    private static int Main(string[] args)
    {
        if (args.Any(argument => argument is "--help" or "-h"))
        {
            PrintUsage();
            return 0;
        }

        if (!TryParseArguments(args, out var forgeDirectory, out var modelsDirectory, out var port, out var error))
        {
            Console.Error.WriteLine(error);
            PrintUsage();
            return 2;
        }

        if (forgeDirectory is null)
        {
            forgeDirectory = FindForgeDirectory();
        }

        if (forgeDirectory is null)
        {
            Console.Error.WriteLine("Could not find a Forge installation containing webui.bat and launch.py.");
            Console.Error.WriteLine("Run ForgeServer.exe --forge-dir \"C:\\path\\to\\sd-webui-forge-PRO\"");
            return 2;
        }

        var batchFile = Path.Combine(forgeDirectory, "webui.bat");
        if (!File.Exists(batchFile) || !File.Exists(Path.Combine(forgeDirectory, "launch.py")))
        {
            Console.Error.WriteLine($"The selected folder is not a Forge installation: {forgeDirectory}");
            return 2;
        }

        if (modelsDirectory is not null && !Directory.Exists(modelsDirectory))
        {
            Console.Error.WriteLine($"The selected models folder does not exist: {modelsDirectory}");
            return 2;
        }

        var modelsArgument = modelsDirectory is null ? string.Empty : $" --model-ref \"{modelsDirectory}\"";
        var arguments = $"/d /c \"\"{batchFile}\" --listen --no-browser --port {port}{modelsArgument}\"";
        var startInfo = new ProcessStartInfo
        {
            FileName = Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe",
            Arguments = arguments,
            WorkingDirectory = forgeDirectory,
            UseShellExecute = false,
            CreateNoWindow = false,
        };

        Console.WriteLine($"Starting the Forge server from: {forgeDirectory}");
        if (modelsDirectory is not null)
        {
            Console.WriteLine($"Using models from: {modelsDirectory}");
        }
        Console.WriteLine($"Listening on the local network at port {port}.");
        Console.WriteLine("Keep this window open while Forge is in use. Press Ctrl+C to stop the server.");

        try
        {
            using var process = Process.Start(startInfo);
            if (process is null)
            {
                Console.Error.WriteLine("Windows did not start webui.bat.");
                return 1;
            }

            process.WaitForExit();
            if (process.ExitCode != 0)
            {
                Console.Error.WriteLine($"Forge exited with code {process.ExitCode}.");
            }

            return process.ExitCode;
        }
        catch (Exception exception) when (exception is InvalidOperationException or System.ComponentModel.Win32Exception)
        {
            Console.Error.WriteLine($"Could not start Forge: {exception.Message}");
            return 1;
        }
    }

    private static bool TryParseArguments(
        string[] args,
        out string? forgeDirectory,
        out string? modelsDirectory,
        out int port,
        out string? error)
    {
        forgeDirectory = null;
        modelsDirectory = null;
        port = DefaultPort;
        error = null;

        for (var index = 0; index < args.Length; index++)
        {
            switch (args[index])
            {
                case "--forge-dir" when index + 1 < args.Length:
                    forgeDirectory = Path.GetFullPath(args[++index]);
                    break;
                case "--model-ref" when index + 1 < args.Length:
                    modelsDirectory = Path.GetFullPath(args[++index]);
                    break;
                case "--port" when index + 1 < args.Length:
                    if (!int.TryParse(args[++index], out port) || port is < 1 or > 65535)
                    {
                        error = "The port must be a number from 1 through 65535.";
                        return false;
                    }

                    break;
                case "--forge-dir":
                case "--model-ref":
                case "--port":
                    error = $"Missing value for {args[index]}.";
                    return false;
                default:
                    error = $"Unknown argument: {args[index]}";
                    return false;
            }
        }

        return true;
    }

    private static string? FindForgeDirectory()
    {
        foreach (var start in new[]
                 {
                     Environment.CurrentDirectory,
                     AppContext.BaseDirectory,
                 })
        {
            var directory = new DirectoryInfo(start);
            while (directory is not null)
            {
                if (File.Exists(Path.Combine(directory.FullName, "webui.bat"))
                    && File.Exists(Path.Combine(directory.FullName, "launch.py")))
                {
                    return directory.FullName;
                }

                directory = directory.Parent;
            }
        }

        return null;
    }

    private static void PrintUsage()
    {
        Console.WriteLine("Forge Server launcher");
        Console.WriteLine("Usage: ForgeServer.exe [--forge-dir <path>] [--model-ref <models-folder>] [--port <port>]");
        Console.WriteLine($"Defaults: detect Forge from the current/parent folders; port {DefaultPort}.");
        Console.WriteLine("The launcher uses the existing Forge Python environment and model files. --model-ref overrides Forge's models folder.");
    }
}
