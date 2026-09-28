# Speak voice lines with the Windows speech engine.
# Usage: powershell -File tts.ps1 <jobs.json>
#   jobs: [{ "out": "x.wav", "voice": "Microsoft David Desktop", "text": "...",
#            "rate": 0, "pitch": "+0%", "hz": 16000 }]
param([string]$jobs)
Add-Type -AssemblyName System.Speech
$list = Get-Content -Raw $jobs | ConvertFrom-Json
foreach ($j in $list) {
    $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo($j.hz, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $s.SetOutputToWaveFile($j.out, $fmt)
    $text = [System.Security.SecurityElement]::Escape($j.text)
    $ssml = "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>" +
            "<voice name='$($j.voice)'><prosody rate='$($j.rate)' pitch='$($j.pitch)'>$text</prosody></voice></speak>"
    $s.SpeakSsml($ssml)
    $s.Dispose()
}
"spoke $($list.Count) lines"
