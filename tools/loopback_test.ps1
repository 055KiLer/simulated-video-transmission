# Loopback test: send pattern to board, listen for return
param(
    [string]$PortName = 'COM10',
    [int]$Baud = 115200
)
$port = New-Object System.IO.Ports.SerialPort($PortName, $Baud, 'None', 8, 'One')
$port.ReadTimeout = 300
$port.WriteTimeout = 800
$port.DtrEnable = $true
$port.RtsEnable = $true
try {
    $port.Open()
} catch {
    Write-Output "OPEN FAILED: $($_.Exception.Message)"
    exit 1
}
Start-Sleep -Milliseconds 300

# clear anything stale
while ($port.BytesToRead -gt 0) { $null = $port.ReadByte() }

# test pattern: recognizable frame-like bytes
$bytes = [byte[]](0xA5,0x1E,0x00,0x07,0x58,0x02,0x03,0x11,0x22,0x33,0x44,0x55,0x66,0x77,0x88,0x99,0xAA,0xBB,0xCC,0xDD,0xEE,0xFF,0x5A,0xA5)
Write-Output ("SENT: " + (($bytes | ForEach-Object { $_.ToString('X2') }) -join ' '))

$port.Write($bytes, 0, $bytes.Length)

# wait for echo
$response = New-Object System.Collections.Generic.List[byte]
$deadline = [DateTime]::Now.AddMilliseconds(1500)
while ([DateTime]::Now -lt $deadline) {
    while ($port.BytesToRead -gt 0) {
        try { $response.Add($port.ReadByte()) } catch { break }
    }
    if ($response.Count -ge $bytes.Length) { break }
    Start-Sleep -Milliseconds 20
}
$port.Close()

if ($response.Count -eq 0) {
    Write-Output "RESULT: NO DATA RETURNED (0 bytes)"
} else {
    $hex = ($response | ForEach-Object { $_.ToString('X2') }) -join ' '
    Write-Output ("RESULT: RECEIVED {0} bytes: {1}" -f $response.Count, $hex)
    $sent = ($bytes | ForEach-Object { $_.ToString('X2') }) -join ' '
    if ($hex -eq $sent) {
        Write-Output "MATCH: PERFECT ECHO - bridge works!"
    } else {
        Write-Output "MISMATCH: received differs from sent"
    }
}
