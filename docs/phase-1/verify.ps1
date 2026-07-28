param(
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$phaseRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $phaseRoot '..\..')).Path
$specPath = Join-Path $phaseRoot 'BUNNY_OS_PHASE_1.md'
$tracePath = Join-Path $phaseRoot 'TRACEABILITY_MATRIX.md'
$a11yPath = Join-Path $phaseRoot 'ACCESSIBILITY_CONFORMANCE_MATRIX.md'
$backlogPath = Join-Path $phaseRoot 'PHASE_2_BACKLOG.md'
$sourcesPath = Join-Path $phaseRoot 'SOURCES.md'
$spec = Get-Content -Raw -LiteralPath $specPath
$trace = Get-Content -Raw -LiteralPath $tracePath
$a11y = Get-Content -Raw -LiteralPath $a11yPath
$backlog = Get-Content -Raw -LiteralPath $backlogPath
$sources = Get-Content -Raw -LiteralPath $sourcesPath
$failures = [System.Collections.Generic.List[string]]::new()
$passes = [System.Collections.Generic.List[string]]::new()

function Test-Sequence {
    param([int[]]$Actual, [int[]]$Expected, [string]$Label)
    $actualText = $Actual -join ','
    $expectedText = $Expected -join ','
    if ($actualText -ne $expectedText) {
        $script:failures.Add("$Label expected [$expectedText], found [$actualText]")
    } else {
        $script:passes.Add("${Label}: $($Expected.Count)")
    }
}

function Require-True {
    param([bool]$Condition, [string]$PassMessage, [string]$FailureMessage)
    if ($Condition) { $script:passes.Add($PassMessage) } else { $script:failures.Add($FailureMessage) }
}

$sectionIds = [regex]::Matches($spec, '(?m)^## ([1-9]|[12][0-9]|3[0-5])\. ') |
    ForEach-Object { [int]$_.Groups[1].Value }
Test-Sequence -Actual $sectionIds -Expected (1..35) -Label 'Numbered sections'

$contractIds = [regex]::Matches($spec, '(?m)^### A\.([0-9]+) ') |
    ForEach-Object { [int]$_.Groups[1].Value }
Test-Sequence -Actual $contractIds -Expected (1..13) -Label 'Interface contracts'

$amendmentStart = $spec.IndexOf('### 31.1 ')
$amendmentEnd = $spec.IndexOf('### 31.2 ')
if ($amendmentStart -lt 0 -or $amendmentEnd -le $amendmentStart) { throw 'Could not isolate §31.1 amendment table' }
$amendmentSection = $spec.Substring($amendmentStart, $amendmentEnd - $amendmentStart)
$amendmentIds = [regex]::Matches($amendmentSection, '(?m)^\| A([0-9]+) \|') |
    ForEach-Object { [int]$_.Groups[1].Value }
Test-Sequence -Actual $amendmentIds -Expected (1..15) -Label 'Requested amendments'

$prototypeIds = [regex]::Matches($spec, '(?m)^\| \*\*P([0-9]+)\*\* \|') |
    ForEach-Object { [int]$_.Groups[1].Value }
Test-Sequence -Actual $prototypeIds -Expected (1..29) -Label 'Prototype registry'

$prototypeOwnerRows = [regex]::Matches($spec, '(?m)^\| P([0-9]+) \| ([^|]+) \|')
$prototypeOwnerFailures = @($prototypeOwnerRows | Where-Object { $_.Groups[2].Value.Trim() -match '\s\+\s|\s/\s' })
Require-True ($prototypeOwnerRows.Count -eq 29 -and $prototypeOwnerFailures.Count -eq 0) 'Prototype accountable owners: 29 singular' "Prototype owner ambiguity: $($prototypeOwnerFailures.Value -join '; ')"

$cIds = [regex]::Matches($trace, '(?m)^\| \*\*C([0-9]+)\*\* \|') |
    ForEach-Object { [int]$_.Groups[1].Value }
$dIds = [regex]::Matches($trace, '(?m)^\| \*\*D([0-9]+)\*\* \|') |
    ForEach-Object { [int]$_.Groups[1].Value }
Test-Sequence -Actual $cIds -Expected (1..16) -Label 'Constitutional trace rows'
Test-Sequence -Actual $dIds -Expected (1..17) -Label 'Decision trace rows'

$adrFiles = @(Get-ChildItem -LiteralPath (Join-Path $phaseRoot 'adr') -Filter '*.md' | Sort-Object Name)
Require-True ($adrFiles.Count -eq 20) 'ADR files: 20' "Expected 20 ADR files, found $($adrFiles.Count)"
$requiredAdrHeaders = @('## Context', '## Decision', '## Alternatives', '## Consequences', '## Risks', '## Validation required', '## Phase 0 principles satisfied')
foreach ($adr in $adrFiles) {
    $text = Get-Content -Raw -LiteralPath $adr.FullName
    if ($text -notmatch '(?m)^\*\*Status:\*\*') { $failures.Add("$($adr.Name): missing Status") }
    foreach ($header in $requiredAdrHeaders) {
        if (-not $text.Contains($header)) { $failures.Add("$($adr.Name): missing $header") }
    }
}
$conditionalAdrs = @('0003-runtime-reuse-strategy.md', '0007-plan-task-persistence.md', '0010-sandbox-technology-strategy.md', '0014-plugin-mcp-isolation.md', '0015-application-compatibility.md')
foreach ($name in $conditionalAdrs) {
    $text = Get-Content -Raw -LiteralPath (Join-Path $phaseRoot "adr\$name")
    if ($text -notmatch '(?m)^\*\*Status:\*\* Proposed') { $failures.Add("$name must remain Proposed pending amendment") }
}
if (-not ($failures | Where-Object { $_ -match '^00[0-9][0-9]-|^001[0-9]-|^0020-' })) { $passes.Add('ADR required fields/status gates: pass') }

$diagramFiles = @(Get-ChildItem -LiteralPath (Join-Path $phaseRoot 'diagrams') -Filter '*.mmd')
Require-True ($diagramFiles.Count -eq 15) 'External Mermaid files: 15' "Expected 15 external Mermaid files, found $($diagramFiles.Count)"
$inlineMermaidCount = [regex]::Matches($spec, '(?m)^```mermaid\s*$').Count
Require-True ($inlineMermaidCount -eq 5) 'Inline Mermaid state machines: 5' "Expected 5 inline Mermaid blocks, found $inlineMermaidCount"

$legacyPattern = 'P-(RT|MEM|UI|LX|PL)-?[0-9]+'
$contentFiles = @(Get-ChildItem -LiteralPath $phaseRoot -Recurse -File | Where-Object { $_.Extension -in @('.md','.mmd') })
$legacyHits = $contentFiles |
    Select-String -Pattern $legacyPattern
Require-True ($null -eq $legacyHits) 'Legacy prototype IDs: 0' "Legacy prototype IDs remain: $($legacyHits -join '; ')"

$stalePhrases = @(
    'all seven terminated',
    'Walked mechanically in §36',
    'WCAG 2.2 AA is enforced by the build',
    'Pass, unverified'
)
foreach ($phrase in $stalePhrases) {
    $hits = $contentFiles | Select-String -SimpleMatch $phrase
    if ($hits) { $failures.Add("Stale phrase '$phrase': $($hits.Path -join ', ')") }
}
if (-not ($failures | Where-Object { $_ -like 'Stale phrase*' })) { $passes.Add('Stale verification phrases: 0') }

$wcagIds = @(
    '1.1.1','1.2.1','1.2.2','1.2.3','1.2.4','1.2.5','1.3.1','1.3.2','1.3.3','1.3.4','1.3.5',
    '1.4.1','1.4.2','1.4.3','1.4.4','1.4.5','1.4.10','1.4.11','1.4.12','1.4.13',
    '2.1.1','2.1.2','2.1.4','2.2.1','2.2.2','2.3.1','2.4.1','2.4.2','2.4.3','2.4.4','2.4.5','2.4.6','2.4.7','2.4.11',
    '2.5.1','2.5.2','2.5.3','2.5.4','2.5.7','2.5.8',
    '3.1.1','3.1.2','3.2.1','3.2.2','3.2.3','3.2.4','3.2.6','3.3.1','3.3.2','3.3.3','3.3.4','3.3.7','3.3.8',
    '4.1.2','4.1.3'
)
$missingWcag = @($wcagIds | Where-Object { $a11y -notmatch "(?m)^\| \*\*$([regex]::Escape($_))(?:\s|\*)" })
Require-True ($missingWcag.Count -eq 0) 'WCAG 2.2 A/AA rows: 55' "Missing WCAG rows: $($missingWcag -join ', ')"

$completeProcessIds = [regex]::Matches($a11y, '(?m)^\| \*\*CP-([0-9]{2})\b') |
    ForEach-Object { [int]$_.Groups[1].Value }
Test-Sequence -Actual $completeProcessIds -Expected (1..14) -Label 'Accessibility complete processes'
Require-True ($a11y.Contains('| **VOICE-PRIMARY** |')) 'Voice compatibility tuple: present' 'Missing VOICE-PRIMARY accessibility compatibility tuple'
Require-True ($a11y.Contains('| **UNSUPPORTED-HOST-NEGATIVE** |')) 'Unsupported-host evidence row: present' 'Missing UNSUPPORTED-HOST-NEGATIVE accessibility evidence row'
Require-True ($a11y.Contains('| **UNKNOWN-AT-NEGATIVE** |')) 'Unknown-AT privacy evidence row: present' 'Missing UNKNOWN-AT-NEGATIVE accessibility evidence row'
Require-True ($a11y.Contains('§11.8 applicability unresolved')) 'EN 301 549 §11.8 decision gate: present' 'Missing EN 301 549 §11.8 authoring-tool applicability gate'

$requiredFiles = @(
    'BUNNY_OS_PHASE_1.md','PHASE_2_BACKLOG.md','TRACEABILITY_MATRIX.md',
    'ACCESSIBILITY_CONFORMANCE_MATRIX.md','SOURCES.md','ADVERSARIAL_REVIEW.md','README.md'
)
foreach ($name in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $phaseRoot $name))) { $failures.Add("Missing companion artifact: $name") }
}

$brokenLinks = [System.Collections.Generic.List[string]]::new()
$mdFiles = @(Get-ChildItem -LiteralPath $phaseRoot -Recurse -File -Filter '*.md')
foreach ($file in $mdFiles) {
    $content = Get-Content -Raw -LiteralPath $file.FullName
    foreach ($match in [regex]::Matches($content, '\[[^\]]*\]\(([^)]+)\)')) {
        $target = $match.Groups[1].Value.Trim().Trim('<','>')
        if ($target -match '^(https?://|mailto:|#)') { continue }
        $target = ($target -split '#', 2)[0]
        if ([string]::IsNullOrWhiteSpace($target)) { continue }
        $target = [System.Uri]::UnescapeDataString($target)
        $resolved = Join-Path $file.DirectoryName $target
        if (-not (Test-Path -LiteralPath $resolved)) { $brokenLinks.Add("$($file.Name) -> $target") }
    }
}
Require-True ($brokenLinks.Count -eq 0) 'Relative Markdown links: pass' "Broken relative links: $($brokenLinks -join '; ')"

$backlogIds = [regex]::Matches($backlog, '(?m)^\*\*((?:S0|A|B|C|D|E|F|G|H|X)-[0-9]+[a-z]?)\s+—') |
    ForEach-Object { $_.Groups[1].Value }
$duplicateBacklogIds = @($backlogIds | Group-Object | Where-Object Count -gt 1 | ForEach-Object Name)
Require-True ($duplicateBacklogIds.Count -eq 0) "Backlog IDs unique: $($backlogIds.Count)" "Duplicate backlog IDs: $($duplicateBacklogIds -join ', ')"

$backlogBlocks = [regex]::Matches(
    $backlog,
    '(?ms)^\*\*((?:S0|A|B|C|D|E|F|G|H|X)-[0-9]+[a-z]?)\s+—.*?(?=^\*\*(?:(?:S0|A|B|C|D|E|F|G|H|X)-[0-9]+[a-z]?)\s+—|^## |\z)'
)
$backlogFieldFailures = [System.Collections.Generic.List[string]]::new()
foreach ($blockMatch in $backlogBlocks) {
    $id = $blockMatch.Groups[1].Value
    $block = $blockMatch.Value
    foreach ($field in @('Owner:', 'Deps:', 'Source:', 'Security:', 'Test:', 'Done when:')) {
        if (-not $block.Contains($field)) { $backlogFieldFailures.Add("$id missing $field") }
    }
    if ($block -notmatch '\*\*P[0-2][^*]*\*\*') { $backlogFieldFailures.Add("$id missing priority") }
    $ownerMatch = [regex]::Match($block, 'Owner:\s*([^·\r\n]+)')
    if (-not $ownerMatch.Success -or $ownerMatch.Groups[1].Value.Trim() -eq '—') {
        $backlogFieldFailures.Add("$id has no accountable owner")
    } elseif ($ownerMatch.Groups[1].Value -match '\s/\s|\s\+\s') {
        $backlogFieldFailures.Add("$id has multiple accountable owners; move others to Contributors/Assurance")
    }
}
Require-True ($backlogFieldFailures.Count -eq 0) "Backlog required fields/accountability: $($backlogBlocks.Count) items" "Backlog field failures: $($backlogFieldFailures -join '; ')"

$sourceIds = [regex]::Matches($sources, '(?m)^\| ([A-Z][A-Z0-9]*-[0-9]+[a-z]?) \|') |
    ForEach-Object { $_.Groups[1].Value }
$duplicateSourceIds = @($sourceIds | Group-Object | Where-Object Count -gt 1 | ForEach-Object Name)
Require-True ($duplicateSourceIds.Count -eq 0) "Source IDs unique: $($sourceIds.Count)" "Duplicate source IDs: $($duplicateSourceIds -join ', ')"

$traceBacklogRefs = [regex]::Matches($trace, '(?<![A-Za-z0-9])((?:S0|A|B|C|D|E|F|G|H|X)-[0-9]+[a-z]?)(?![A-Za-z0-9])') |
    ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
$missingTraceBacklogRefs = @($traceBacklogRefs | Where-Object { $_ -notin $backlogIds })
Require-True ($missingTraceBacklogRefs.Count -eq 0) "Trace backlog references valid: $($traceBacklogRefs.Count)" "Trace references missing backlog IDs: $($missingTraceBacklogRefs -join ', ')"

if ($failures.Count -gt 0) {
    foreach ($failure in $failures) { Write-Output "FAIL: $failure" }
    exit 1
}

if (-not $Quiet) {
    foreach ($pass in $passes) { Write-Output "PASS: $pass" }
}
Write-Output "PASS: Phase 1 structural verification completed ($($passes.Count) checks). Mermaid parsing is a separate pinned-tool run."
