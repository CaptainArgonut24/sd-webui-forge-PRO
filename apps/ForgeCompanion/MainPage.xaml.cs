namespace ForgeCompanion;

public partial class MainPage : ContentPage
{
    private bool _initialized;

    public MainPage()
    {
        InitializeComponent();
    }

    protected override void OnAppearing()
    {
        base.OnAppearing();

        if (_initialized)
        {
            return;
        }

        _initialized = true;
        var savedUrl = Preferences.Default.Get("serverUrl", string.Empty);
#if WINDOWS
        var serverUrl = string.IsNullOrWhiteSpace(savedUrl)
            ? "http://127.0.0.1:7860/"
            : savedUrl;
        ServerUrlEntry.Text = serverUrl;
        ConnectToServer(serverUrl);
#else
        ServerUrlEntry.Text = savedUrl;
        if (!string.IsNullOrWhiteSpace(savedUrl))
        {
            ConnectToServer(savedUrl);
        }
        else
        {
            StatusLabel.Text = "Enter the Forge server URL to connect.";
        }
#endif
    }

    private async void OnConnectClicked(object? sender, EventArgs e)
    {
        if (ConnectToServer(ServerUrlEntry.Text))
        {
            StatusLabel.Text = "Loading Forge...";
        }
        else
        {
            await DisplayAlertAsync(
                "Invalid server URL",
                "Enter a full HTTP or HTTPS address, such as http://192.168.1.25:7860.",
                "OK");
        }
    }

    private void OnReloadClicked(object? sender, EventArgs e)
    {
        if (ForgeWebView.Source is not null)
        {
            ForgeWebView.Reload();
        }
    }

    private void OnWebViewNavigated(object? sender, WebNavigatedEventArgs e)
    {
        StatusLabel.Text = e.Result == WebNavigationResult.Success
            ? "Connected to Forge."
            : $"Could not load Forge ({e.Result}). Check the server URL, Wi-Fi, and Windows Firewall.";
    }

    private bool ConnectToServer(string? value)
    {
        if (!Uri.TryCreate(value?.Trim(), UriKind.Absolute, out var uri)
            || (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps)
            || string.IsNullOrWhiteSpace(uri.Host))
        {
            return false;
        }

        var normalizedUrl = uri.AbsoluteUri;
        ServerUrlEntry.Text = normalizedUrl;
        Preferences.Default.Set("serverUrl", normalizedUrl);
        ForgeWebView.Source = new UrlWebViewSource { Url = normalizedUrl };
        ForgeWebView.IsVisible = true;
        EmptyStatePanel.IsVisible = false;
        return true;
    }

    protected override bool OnBackButtonPressed()
    {
        if (ForgeWebView.IsVisible && ForgeWebView.CanGoBack)
        {
            ForgeWebView.GoBack();
            return true;
        }

        return base.OnBackButtonPressed();
    }
}
