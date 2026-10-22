// Original Windows launcher. No game code or data.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text.RegularExpressions;
using System.Windows.Forms;

internal sealed class Launcher : Form {
    readonly string root = AppDomain.CurrentDomain.BaseDirectory;
    readonly ComboBox rate = new ComboBox();
    readonly Button play = new Button();
    readonly Label status = new Label();
    readonly string baseRate;
    Process game;

    Launcher() {
        string rateFile = Path.Combine(root, "launcher-fps.txt");
        baseRate = File.Exists(rateFile) && File.ReadAllText(rateFile).Trim() == "60" ? "60" : "30";
        Text = "AC-Recomp";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        Font = new Font("Segoe UI", 10);
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(510, 340);
        MinimumSize = Size;
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        var layout = new TableLayoutPanel {
            Dock = DockStyle.Fill, Padding = new Padding(28), ColumnCount = 1, RowCount = 6
        };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 46));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 45));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 50));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 46));
        layout.Controls.Add(new Label {
            Text = "AC-Recomp", AutoSize = true, Font = new Font("Segoe UI", 22, FontStyle.Bold)
        });
        layout.Controls.Add(new Label {
            Text = "Your game, built on your PC.\r\nChoose a frame rate, then play.", AutoSize = true
        });
        var choice = new FlowLayoutPanel { Dock = DockStyle.Fill };
        choice.Controls.Add(new Label { Text = "&Frame rate", AutoSize = true, Padding = new Padding(0, 5, 12, 0) });
        rate.DropDownStyle = ComboBoxStyle.DropDownList;
        rate.Width = 200;
        rate.Items.Add(baseRate + " fps");
        if (File.Exists(Path.Combine(root, "astral-60fps.exe"))) rate.Items.Add("60 fps (experimental)");
        rate.SelectedIndex = 0;
        string settings = Path.Combine(root, "data", "settings.ini");
        if (File.Exists(settings) && rate.Items.Count > 1 &&
            Regex.IsMatch(File.ReadAllText(settings), @"(?m)^\s*fps\s*=\s*60\s*(?:#.*)?$")) rate.SelectedIndex = 1;
        choice.Controls.Add(rate);
        layout.Controls.Add(choice);
        play.Text = "&Play";
        play.Width = 200;
        play.Height = 40;
        play.Click += delegate { StartGame(); };
        layout.Controls.Add(play);
        status.AutoSize = true;
        status.MaximumSize = new Size(450, 0);
        status.Text = "Connect your controller before starting.";
        layout.Controls.Add(status);
        var links = new FlowLayoutPanel { Dock = DockStyle.Fill };
        var folder = new Button { Text = "&Open install folder", AutoSize = true };
        folder.Click += delegate { Process.Start("explorer.exe", "\"" + root.TrimEnd('\\') + "\""); };
        var quit = new Button { Text = "&Quit", AutoSize = true };
        quit.Click += delegate { Close(); };
        links.Controls.Add(folder);
        links.Controls.Add(quit);
        layout.Controls.Add(links);
        Controls.Add(layout);
        AcceptButton = play;
        CancelButton = quit;
        FormClosing += delegate(object sender, FormClosingEventArgs e) {
            if (game != null && !game.HasExited) {
                MessageBox.Show(this, "Close the game window before quitting the launcher.", "Game is running");
                e.Cancel = true;
            }
        };
    }
    void StartGame() {
        try {
            string executable = Path.Combine(root, rate.SelectedIndex == 1 ? "astral-60fps.exe" : "astral.exe");
            if (!File.Exists(executable) || !Directory.Exists(Path.Combine(root, "data", "extract", "romfs")))
                throw new IOException("Game files are missing. Run AC-Recomp Setup again to finish the build.");
            string settings = Path.Combine(root, "data", "settings.ini");
            string text = File.Exists(settings) ? File.ReadAllText(settings) : "";
            text = Regex.Replace(text, @"(?m)^\s*fps\s*=.*\r?\n?", "");
            string selectedRate = rate.SelectedIndex == 1 ? "60" : baseRate;
            File.WriteAllText(settings, text.TrimEnd() + "\r\nfps = " + selectedRate + "\r\n");
            var info = new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                @"WindowsPowerShell\v1.0\powershell.exe"),
                "-NoProfile -ExecutionPolicy Bypass -File \"" + Path.Combine(root, "run-ac-recomp.ps1") + "\"") {
                WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true
            };
            string data = Path.Combine(root, "data");
            info.EnvironmentVariables["NX_DATA_ROOT"] = data;
            info.EnvironmentVariables["NX_SHARED_FONT_DIR"] = Path.Combine(data, "shared-fonts");
            info.EnvironmentVariables["NX_NVN_FORMAT_PROFILE"] = Path.Combine(data, "astral.profile");
            info.EnvironmentVariables["NX_NVN_REAL"] = "1";
            info.EnvironmentVariables["NX_FPS"] = selectedRate;
            // Preserve diagnostic overrides, and provide a persistent default failure log.
            if (String.IsNullOrEmpty(info.EnvironmentVariables["NX_LOG"]))
                info.EnvironmentVariables["NX_LOG"] = Path.Combine(root, "game.log");
            game = Process.Start(info);
            play.Enabled = rate.Enabled = false;
            status.Text = "Game is running. Close its window to return here.";
            var timer = new Timer { Interval = 500 };
            timer.Tick += delegate {
                if (game.HasExited) {
                    timer.Stop(); timer.Dispose();
                    status.Text = game.ExitCode == 0 ? "Ready to play." :
                        "Game stopped (code " + game.ExitCode + "). See game.log in the install folder.";
                    game.Dispose(); game = null;
                    play.Enabled = rate.Enabled = true;
                }
            };
            timer.Start();
        } catch (Exception e) {
            MessageBox.Show(this, e.Message, "Could not start AC-Recomp", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
    [STAThread] static void Main() {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new Launcher());
    }
}
