using NAudio.CoreAudioApi;
using NAudio.Wave;

if (args.Length == 1 && args[0] == "--help")
{
    Console.WriteLine("WASAPI default-device loopback: AudioCapture <seconds 1..3600> <output.wav>");
    return 0;
}
if (args.Length != 2 || !int.TryParse(args[0], out var seconds) || seconds < 1 || seconds > 3600)
{
    Console.Error.WriteLine("Usage: AudioCapture <seconds 1..3600> <output.wav>");
    return 2;
}
try
{
    using var enumerator = new MMDeviceEnumerator();
    using var device = enumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia);
    if (!device.FriendlyName.Contains("VB-Audio", StringComparison.OrdinalIgnoreCase))
        throw new InvalidOperationException("Default playback endpoint is not VB-Audio: " + device.FriendlyName);
    using var capture = new WasapiLoopbackCapture(device);
    using var writer = new WaveFileWriter(args[1], capture.WaveFormat);
    // WASAPI omits idle buffers. Place captured PCM on the wall-clock timeline
    // and fill those omitted intervals with digital silence (never synthetic tone).
    var stopped = new TaskCompletionSource<Exception?>(TaskCreationOptions.RunContinuationsAsynchronously);
    long written = 0, captured = 0;
    long limit = (long)seconds * capture.WaveFormat.AverageBytesPerSecond;
    var zeros = new byte[16384];
    var clock = new System.Diagnostics.Stopwatch();
    void FillTo(long position)
    {
        while (written < position)
        {
            int count = (int)Math.Min(zeros.Length, position - written);
            writer.Write(zeros, 0, count);
            written += count;
        }
    }
    capture.DataAvailable += (_, e) =>
    {
        long end = (long)(clock.Elapsed.TotalSeconds * capture.WaveFormat.AverageBytesPerSecond);
        end -= end % capture.WaveFormat.BlockAlign;
        FillTo(Math.Min(limit, Math.Max(0, end - e.BytesRecorded)));
        int count = (int)Math.Min(e.BytesRecorded, limit - written);
        if (count > 0) { writer.Write(e.Buffer, 0, count); written += count; captured += count; }
    };
    capture.RecordingStopped += (_, e) => stopped.TrySetResult(e.Exception);
    Console.WriteLine($"WASAPI loopback endpoint={device.FriendlyName}, format={capture.WaveFormat}, seconds={seconds}");
    clock.Start();
    capture.StartRecording();
    var duration = Task.Delay(TimeSpan.FromSeconds(seconds));
    await Task.WhenAny(duration, stopped.Task);
    bool early = !duration.IsCompleted;
    capture.StopRecording();
    var failure = await stopped.Task.WaitAsync(TimeSpan.FromSeconds(10));
    if (failure != null) throw failure;
    if (early) throw new InvalidOperationException("WASAPI stopped before the requested duration");
    FillTo(limit);
    writer.Flush();
    Console.WriteLine($"Captured PCM bytes={captured}, timeline bytes={written}, duration={written / (double)capture.WaveFormat.AverageBytesPerSecond:F3}s (idle gaps padded with silence)");
    return 0;
}
catch (Exception e)
{
    Console.Error.WriteLine(e.ToString());
    return 1;
}
