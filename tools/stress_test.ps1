# Stress test for the UART bridge (standard loopback wiring assumed)
# Phase 1: size sweep with random payloads
# Phase 2: wrap-around crossing (cumulative > 512 bytes in chunks)
# Phase 3: sustained 30Hz stream (~40s), byte-perfect verification per frame
param(
    [string]$PortName = 'COM10',
    [int]$Baud = 115200
)

$ErrorActionPreference = 'Stop'
$port = New-Object System.IO.Ports.SerialPort($PortName, $Baud, 'None', 8, 'One')
$port.ReadTimeout = 50
$port.WriteTimeout = 2000
$port.DtrEnable = $true
$port.RtsEnable = $true
try { $port.Open() } catch { Write-Output "OPEN FAILED: $($_.Exception.Message)"; exit 1 }
Start-Sleep -Milliseconds 300
while ($port.BytesToRead -gt 0) { $null = $port.ReadByte() }

$rand = New-Object System.Random(20261015)
$script:totalTx = 0; $script:totalRx = 0; $script:failCount = 0

function Send-Verify([byte[]]$data, [int]$timeoutMs) {
    # drain stale bytes from any previous timeout
    while ($port.BytesToRead -gt 0) { $null = $port.ReadByte() }
    $port.Write($data, 0, $data.Length)
    $script:totalTx += $data.Length
    $got = New-Object System.Collections.Generic.List[byte]
    $deadline = [DateTime]::Now.AddMilliseconds($timeoutMs)
    while ($got.Count -lt $data.Length -and [DateTime]::Now -lt $deadline) {
        while ($port.BytesToRead -gt 0) { $got.Add($port.ReadByte()) }
        Start-Sleep -Milliseconds 2
    }
    $script:totalRx += $got.Count
    if ($got.Count -ne $data.Length) { return "LEN($($got.Count)/$($data.Length))" }
    for ($i = 0; $i -lt $data.Length; $i++) {
        if ($got[$i] -ne $data[$i]) { return "BYTE[$i] got $('{0:X2}' -f $got[$i]) want $('{0:X2}' -f $data[$i])" }
    }
    return $null
}

# ---------- Phase 1: size sweep ----------
Write-Output "== Phase 1: size sweep (random payloads) =="
foreach ($size in @(1, 2, 7, 24, 39, 64, 100)) {
    for ($rep = 0; $rep -lt 3; $rep++) {
        $buf = New-Object byte[] $size
        $rand.NextBytes($buf)
        $r = Send-Verify $buf 1000
        if ($r) { Write-Output ("  FAIL size={0} rep={1}: {2}" -f $size, $rep, $r); $script:failCount++ }
        Start-Sleep -Milliseconds 10
    }
}
Write-Output ("  Phase1 done. tx={0} rx={1} fail={2}" -f $script:totalTx, $script:totalRx, $script:failCount)

# ---------- Phase 2: wrap-around crossing ----------
Write-Output "== Phase 2: ring buffer wrap (12 x 60B, cumulative 720B > 512) =="
$p2fail = 0
for ($c = 0; $c -lt 12; $c++) {
    $buf = New-Object byte[] 60
    $rand.NextBytes($buf)
    $r = Send-Verify $buf 1000
    if ($r) { Write-Output ("  FAIL chunk={0}: {1}" -f $c, $r); $p2fail++ }
    Start-Sleep -Milliseconds 20
}
$script:failCount += $p2fail
Write-Output ("  Phase2 done. cumulative tx={0} rx={1} fail={2}" -f $script:totalTx, $script:totalRx, $p2fail)

# ---------- Phase 3: sustained 30 Hz ----------
Write-Output "== Phase 3: sustained 30Hz, 1200 frames x 24B (~40 s) =="
$p3fail = 0; $p3tx = 0; $p3rx = 0
$frame = New-Object byte[] 24
for ($f = 0; $f -lt 1200; $f++) {
    $rand.NextBytes($frame)
    $r = Send-Verify $frame 1000
    if ($r) { $p3fail++; if ($p3fail -le 5) { Write-Output ("  FAIL frame={0}: {1}" -f $f, $r) } }
    Start-Sleep -Milliseconds 33
}
$script:failCount += $p3fail
Write-Output ("  Phase3 done. tx={0} rx={1} fail={2}" -f $script:totalTx, $script:totalRx, $p3fail)

$port.Close()
Write-Output ("==== SUMMARY: total tx={0}B rx={1}B failed-chunks={2} ====" -f $script:totalTx, $script:totalRx, $script:failCount)
if ($script:failCount -eq 0 -and $script:totalTx -eq $script:totalRx) {
    Write-Output "VERDICT: PASS - bridge is byte-perfect under stress"
} else {
    Write-Output "VERDICT: FAIL - see failures above"
}
