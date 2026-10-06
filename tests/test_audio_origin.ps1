# Run against a disposable synthetic receiver bound to host loopback:19090.
# This tests the compiled OP25 WebSocket handshake, not actual RF or audio.
param([int]$Port = 19090)
$ErrorActionPreference = 'Stop'
function Get-HandshakeStatus([string]$Origin) {
    $taskClient = [Net.Sockets.TcpClient]::new('127.0.0.1', $Port)
    try {
        $taskClient.ReceiveTimeout = 5000
        $taskStream = $taskClient.GetStream()
        $taskWriter = [IO.StreamWriter]::new($taskStream, [Text.Encoding]::ASCII)
        $taskWriter.NewLine = "`r`n"
        $taskWriter.AutoFlush = $true
        $taskWebSocketKey = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes('the sample nonce'))
        @('GET / HTTP/1.1', "Host: 127.0.0.1:$Port", 'Upgrade: websocket',
          'Connection: Upgrade', "Sec-WebSocket-Key: $taskWebSocketKey",
          'Sec-WebSocket-Version: 13') | ForEach-Object { $taskWriter.WriteLine($_) }
        if ($Origin) { $taskWriter.WriteLine("Origin: $Origin") }
        $taskWriter.WriteLine('')
        $taskReader = [IO.StreamReader]::new($taskStream, [Text.Encoding]::ASCII)
        return $taskReader.ReadLine()
    } finally {
        $taskClient.Close()
    }
}
$taskAllowed = @('http://127.0.0.1:8080', 'http://localhost:8080')
foreach ($taskOrigin in $taskAllowed) {
    $taskStatus = Get-HandshakeStatus $taskOrigin
    if ($taskStatus -notmatch '^HTTP/1\.[01] 101 ') { throw "Expected accepted handshake for $taskOrigin; got $taskStatus" }
}
foreach ($taskOrigin in @('https://evil.example', 'http://127.0.0.1:8081', '')) {
    $taskStatus = Get-HandshakeStatus $taskOrigin
    if ($taskStatus -match '^HTTP/1\.[01] 101 ') { throw "Unexpected accepted handshake for '$taskOrigin'" }
}
Write-Host 'PASS: audio WebSocket accepts only the exact local dashboard origins'
