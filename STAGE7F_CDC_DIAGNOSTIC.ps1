param(
    [string]$ProjectRoot = (Get-Location).Path
)

$ErrorActionPreference = "Continue"

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outDir = Join-Path $ProjectRoot "artifacts\stage7f"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$outFile = Join-Path $outDir "stage7f_diagnostic_$timestamp.txt"

function Add-Section {
    param([string]$Title)
    "`r`n================================================================" | Tee-Object -FilePath $outFile -Append
    $Title | Tee-Object -FilePath $outFile -Append
    "================================================================" | Tee-Object -FilePath $outFile -Append
}

function Capture {
    param([scriptblock]$Command)
    try {
        & $Command 2>&1 | Out-String -Width 260 | Tee-Object -FilePath $outFile -Append
    }
    catch {
        $_ | Out-String | Tee-Object -FilePath $outFile -Append
    }
}

"PharmStock V2 - Stage 7F CDC Diagnostic" | Set-Content -Path $outFile
"Generated: $(Get-Date -Format o)" | Add-Content -Path $outFile
"Read-only diagnostic: YES (no PostgreSQL/Kafka data mutation)" | Add-Content -Path $outFile

Add-Section "1) Docker containers"
Capture { docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" }

Add-Section "2) Kafka Connect connector status"
Capture {
    $status = Invoke-RestMethod -Method Get -Uri "http://localhost:8083/connectors/pharmstock-postgres-cdc/status" -TimeoutSec 15
    $status | ConvertTo-Json -Depth 20
}

Add-Section "3) Kafka Connect connector config (password redacted)"
Capture {
    $cfg = Invoke-RestMethod -Method Get -Uri "http://localhost:8083/connectors/pharmstock-postgres-cdc/config" -TimeoutSec 15
    if ($null -ne $cfg.'database.password') {
        $cfg.'database.password' = "<REDACTED>"
    }
    $cfg | ConvertTo-Json -Depth 20
}

Add-Section "4) PostgreSQL logical replication slot"
Capture {
    docker exec pharmstock-postgres psql -U pharmstock_admin -d pharmstock_ops -P pager=off -c "SELECT slot_name, plugin, slot_type, active, restart_lsn, confirmed_flush_lsn FROM pg_replication_slots WHERE slot_name='pharmstock_cdc_slot';"
}

Add-Section "5) Publication tables"
Capture {
    docker exec pharmstock-postgres psql -U pharmstock_admin -d pharmstock_ops -P pager=off -c "SELECT schemaname || '.' || tablename AS published_table FROM pg_publication_tables WHERE pubname='pharmstock_cdc_publication' ORDER BY 1;"
}

Add-Section "6) Supplier table replica identity and primary key"
Capture {
    docker exec pharmstock-postgres psql -U pharmstock_admin -d pharmstock_ops -P pager=off -c "SELECT c.relreplident, i.indexrelid::regclass AS primary_key_index FROM pg_class c LEFT JOIN pg_index i ON i.indrelid=c.oid AND i.indisprimary WHERE c.oid='procurement.supplier'::regclass;"
}

Add-Section "7) Kafka supplier topic describe"
Capture {
    docker exec pharmstock-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic pharmstock.ops.procurement.supplier
}

Add-Section "8) Kafka supplier topic offsets"
Capture {
    docker exec pharmstock-kafka /opt/kafka/bin/kafka-get-offsets.sh --bootstrap-server localhost:9092 --topic pharmstock.ops.procurement.supplier
}

Add-Section "9) Raw supplier-topic messages (up to 30, from beginning)"
Capture {
    docker exec pharmstock-kafka /opt/kafka/bin/kafka-console-consumer.sh `
        --bootstrap-server localhost:9092 `
        --topic pharmstock.ops.procurement.supplier `
        --from-beginning `
        --max-messages 30 `
        --timeout-ms 7000 `
        --property print.key=true `
        --property print.value=true `
        --property print.partition=true `
        --property print.offset=true `
        --property key.separator=" | "
}

Add-Section "10) Debezium log signals (last 400 lines, filtered)"
Capture {
    docker logs pharmstock-connect --tail 400 2>&1 |
        Select-String -Pattern "ERROR|WARN|Exception|publication|slot|supplier|stream|topic|LSN|Started|starting"
}

Add-Section "11) Current WAL / slot progress"
Capture {
    docker exec pharmstock-postgres psql -U pharmstock_admin -d pharmstock_ops -P pager=off -c "SELECT pg_current_wal_lsn() AS current_wal_lsn; SELECT slot_name, active, restart_lsn, confirmed_flush_lsn FROM pg_replication_slots WHERE slot_name='pharmstock_cdc_slot';"
}

"`r`nDIAGNOSTIC_COMPLETE=YES" | Add-Content -Path $outFile
"DOWNLOAD_PATH=$outFile" | Add-Content -Path $outFile

Write-Host ""
Write-Host "Stage 7F diagnostic completed."
Write-Host "DOWNLOAD_PATH=$outFile"
