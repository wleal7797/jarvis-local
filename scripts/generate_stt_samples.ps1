# Genera audios de prueba (WAV 16 kHz mono) con la voz en español de Windows.
# Uso:  .\scripts\generate_stt_samples.ps1        → data\stt\01.wav, 02.wav, …
# Las frases están en eval\stt_frases.txt. Los audios no se suben a Git (data/ se ignora).

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "data\stt"
New-Item -ItemType Directory -Force -Path $out | Out-Null

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like "es-*" } | Select-Object -First 1
if (-not $voice) { throw "No hay voces en español instaladas en Windows." }
$synth.SelectVoice($voice.VoiceInfo.Name)
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)

$i = 0
Get-Content (Join-Path $root "eval\stt_frases.txt") -Encoding UTF8 | Where-Object { $_.Trim() } | ForEach-Object {
    $i++
    $file = Join-Path $out ("{0:D2}.wav" -f $i)
    $synth.SetOutputToWaveFile($file, $format)
    $synth.Speak($_)
}
$synth.SetOutputToNull()
Write-Output "Generados $i audios con la voz $($voice.VoiceInfo.Name) en $out"
