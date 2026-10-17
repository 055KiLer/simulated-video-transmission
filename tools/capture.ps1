# Capture raw bytes from a serial port for N seconds, save to file
param(
    [string]$PortName = 'COM10',
    [int]$Baud = 921600,
    [int]$Seconds = 10,
    [string]$OutFile = 'capture.bin'
)
$port = New-Object System.IO.Ports.SerialPort($PortName, $Baud, 'None', 8, 'One')
$port.ReadTimeout = 100
$port.DtrEnable = $true
$port.RtsEnable = $true
try { $port.Open() } catch { Write-Output "OPEN FAILED: $($_.Exception.Message)"; exit 1 }
Start-Sleep -Milliseconds 200
while ($port.BytesToRead -gt 0) { $null = $port.ReadByte() }

$bytes = New-Object System.Collections.Generic.List[byte]
$deadline = [DateTime]::Now.AddSeconds($Seconds)
while ([DateTime]::Now -lt $deadline) {
    while ($port.BytesToRead -gt 0) { $bytes.Add($port.ReadByte()) }
    Start-Sleep -Milliseconds 5
}
$port.Close()

[System.IO.File]::WriteAllBytes($OutFile, $bytes.ToArray())
Write-Output ("CAPTURED {0} bytes in {1}s -> {2}" -f $bytes.Count, $Seconds, $OutFile)
if ($bytes.Count -gt 0) {
    $show = [Math]::Min(48, $bytes.Count)
    $hex = ($bytes.GetRange(0, $show) | ForEach-Object { $_.ToString('X2') }) -join ' '
    Write-Output ("FIRST {0} bytes: {1}" -f $show, $hex)
}
