# Intelligibility check: recognise each wav with Windows dictation and print
# "<file>`t<confidence>`t<heard text>". Usage: powershell -File asr_check.ps1 <dir>
param([string]$dir)
Add-Type -AssemblyName System.Speech
foreach ($f in Get-ChildItem -Path $dir -Filter *.wav | Sort-Object Name) {
    $r = New-Object System.Speech.Recognition.SpeechRecognitionEngine([System.Globalization.CultureInfo]'en-US')
    $r.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
    $r.SetInputToWaveFile($f.FullName)
    $heard = @(); $conf = 0.0
    while ($true) {
        try { $res = $r.Recognize() } catch { break }
        if ($res -eq $null) { break }
        $heard += $res.Text; $conf = [Math]::Max($conf, $res.Confidence)
    }
    $r.Dispose()
    "{0}`t{1:N2}`t{2}" -f $f.BaseName, $conf, ($heard -join ' ')
}
