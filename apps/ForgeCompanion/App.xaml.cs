using Microsoft.Extensions.DependencyInjection;

namespace ForgeCompanion;

public partial class App : Application
{
	public App()
	{
		InitializeComponent();
	}

	protected override Window CreateWindow(IActivationState? activationState)
	{
		return new Window(new MainPage())
		{
			Title = "Forge Companion",
			Width = 1440,
			Height = 960,
		};
	}
}