using System.IO;
using System.Windows;
using Microsoft.Win32;

namespace ShedLink.Manager.App;

public partial class DiagnosticPreviewWindow : Window
{
    public DiagnosticPreviewWindow(string report)
    {
        InitializeComponent();
        ReportText.Text = report;
    }

    private void SaveButton_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new SaveFileDialog
        {
            Title = "Сохранить диагностический отчёт",
            FileName = $"shedlink-diagnostic-{DateTime.Now:yyyyMMdd-HHmmss}.json",
            DefaultExt = ".json",
            Filter = "JSON (*.json)|*.json",
        };
        if (dialog.ShowDialog(this) != true)
        {
            return;
        }
        File.WriteAllText(dialog.FileName, ReportText.Text);
        DialogResult = true;
    }
}
