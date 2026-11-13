<#
.SYNOPSIS
AC-22.3 smoke workflow: ingest, process, chunk, index, search, ask, withdraw and ask again, using only techdocqa commands.

.DESCRIPTION
Runs the configured real models, so Ollama must be running with both pinned models. Everything happens in a new
temporary directory with its own registry and index; the project's data directory is never touched. Two small Markdown
documents are written: one holds the answer and the other is unrelated. After the answering document is withdrawn,
the same question must be refused as no_evidence without a model call (AC-21.1). Exits 0 when every check passes and 1
otherwise. The temporary directory is removed unless -Keep is given.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts\cli_smoke.ps1
#>
param(
    [string]$Cli = (Join-Path $PSScriptRoot "..\.venv\Scripts\techdocqa.exe"),
    [string]$Config = (Join-Path $PSScriptRoot "..\config\default.toml"),
    [switch]$Keep
)

$ErrorActionPreference = "Stop"
$work = Join-Path ([IO.Path]::GetTempPath()) ("techdocqa-smoke-" + [guid]::NewGuid().ToString("N"))
$corpus = Join-Path $work "corpus"
$data = Join-Path $work "data"
New-Item -ItemType Directory -Force -Path $corpus, $data | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding $false

function Write-Utf8([string]$Path, [string]$Text) {
    # Without a byte order mark, which TOML and the Markdown title rules do not expect.
    [IO.File]::WriteAllText($Path, $Text, $utf8)
}

# The overlay changes only where documents and runtime data live; models and thresholds come from the configuration.
$overlay = Join-Path $work "smoke.toml"
Write-Utf8 $overlay "allowed_directories = ['$corpus']`ndata_directory = '$data'`n"
Write-Utf8 (Join-Path $corpus "halcyon.md") @"
# Halcyon scheduler guide

## Retries

The Halcyon scheduler retries a failed job three times and waits 45 seconds between attempts. The halcyon.retry.limit setting changes the number of retries, and the halcyon.retry.delay setting changes the wait.

When every retry fails, Halcyon marks the job as abandoned and records the last error message.
"@
Write-Utf8 (Join-Path $corpus "seeds.md") @"
# Seed starting notes

Tomato seeds germinate best in moist soil kept between 21 and 27 degrees Celsius. Seedlings need about fourteen hours of light each day, and they should be hardened off outdoors for a week before transplanting.
"@

$question = "How many times does the Halcyon scheduler retry a failed job?"
$checks = New-Object System.Collections.Generic.List[object]
$failed = $false

function Invoke-TechDocQA([string[]]$Arguments, [int]$Expect = 0) {
    $output = & $Cli @Arguments --config $Config --profile $overlay
    $code = $LASTEXITCODE
    if ($code -ne $Expect) {
        throw "techdocqa $($Arguments[0]) exited $code, expected $Expect"
    }
    return (($output | Out-String) | ConvertFrom-Json)
}

function Format-Relevance($Sufficiency) {
    # A single-mode gate reports one top score; the hybrid gate reports one per component it judges (P10-3).
    if ($null -ne $Sufficiency.top_score) { return "$($Sufficiency.top_score) against $($Sufficiency.min_top_score)" }
    $parts = foreach ($component in $Sufficiency.components.PSObject.Properties) {
        "$($component.Name) $($component.Value.top_score) against $($component.Value.min_top_score)"
    }
    return ($parts -join ", ")
}

function Test-Step([string]$Name, [bool]$Passed, [string]$Detail) {
    $script:checks.Add([pscustomobject]@{ Step = $Name; Result = $(if ($Passed) { "pass" } else { "FAIL" }); Detail = $Detail })
    if (-not $Passed) { $script:failed = $true }
}

try {
    $halcyon = (Invoke-TechDocQA @("ingest", (Join-Path $corpus "halcyon.md"))).outcomes[0]
    $seeds = (Invoke-TechDocQA @("ingest", (Join-Path $corpus "seeds.md"))).outcomes[0]
    $documentId = $halcyon.result.document_id
    Test-Step "ingest" ($halcyon.status -eq "processed" -and $seeds.status -eq "processed") "2 documents registered"
    foreach ($stage in "process", "chunk", "index") {
        $run = (Invoke-TechDocQA @($stage)).run
        Test-Step $stage ($run.failed -eq 0 -and $run.status -eq "completed") "$($run.status): $($run.processed) processed, $($run.failed) failed"
    }

    $found = Invoke-TechDocQA @("search", "Halcyon retry limit", "--mode", "vector")
    Test-Step "search" ($found.results.Count -gt 0 -and $found.results[0].document_id -eq $documentId) "$($found.results.Count) results, top from the Halcyon guide"

    $answer = Invoke-TechDocQA @("ask", $question)
    $cited = @($answer.citations | Where-Object { $_.document_id -eq $documentId }).Count
    Test-Step "ask" ($answer.status -eq "answered" -and $cited -gt 0 -and $answer.sufficiency.passed) `
        "$($answer.status), $cited citation(s) of the Halcyon guide, relevance $(Format-Relevance $answer.sufficiency)"

    $withdrawn = Invoke-TechDocQA @("withdraw", $documentId, "--reason", "CLI smoke test withdrawal")
    Test-Step "withdraw" ($withdrawn.status -eq "withdrawn") $withdrawn.status

    $refused = Invoke-TechDocQA @("ask", $question)
    Test-Step "ask after withdraw" ($refused.status -eq "no_evidence" -and -not $refused.llm_called) `
        "$($refused.status) ($($refused.reason)), model called: $($refused.llm_called), relevance $(Format-Relevance $refused.sufficiency)"

    $status = Invoke-TechDocQA @("status", "--document-id", $documentId)
    Test-Step "status" ($status.document.status -eq "withdrawn") $status.document.status
}
catch {
    Test-Step "command" $false $_.Exception.Message
}
finally {
    $checks | Format-Table -AutoSize | Out-String -Width 200 | Write-Output
    if ($Keep) {
        Write-Output "Kept $work"
    }
    else {
        Remove-Item -Recurse -Force -Path $work
    }
}

if ($failed) { exit 1 }
exit 0
