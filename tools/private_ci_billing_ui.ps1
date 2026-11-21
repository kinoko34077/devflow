<#
Fixed read-only browser adapter for private_ci_billing_ui.py (#752).
Uses the existing interactive Chrome session; no cookies, tokens, CDP or
credential extraction. Only navigates the two GitHub personal billing URLs
and invokes the Actions product selector. Never invokes a settings mutation.
#>
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$')]
    [string]$Account
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

function Test-BillingAddress($window, [string[]]$paths) {
    $cond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Edit
    )
    foreach ($edit in $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)) {
        # Never read a web document's input fields. Only the browser toolbar.
        $ancestor = [System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($edit)
        $insideDocument = $false
        $depth = 0
        while ($null -ne $ancestor -and $depth -lt 32) {
            if ($ancestor.Current.ControlType -eq [System.Windows.Automation.ControlType]::Document) {
                $insideDocument = $true
                break
            }
            if ($ancestor.Current.ControlType -eq [System.Windows.Automation.ControlType]::Window) { break }
            $ancestor = [System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($ancestor)
            $depth++
        }
        if ($insideDocument -or $depth -ge 32) { continue }
        # Chrome's address control in the English and Japanese UI.
        $jaAddress = (-join @([char]0x30a2, [char]0x30c9, [char]0x30ec, [char]0x30b9, [char]0x30d0, [char]0x30fc))
        $jaSearch = (-join @([char]0x30a2, [char]0x30c9, [char]0x30ec, [char]0x30b9, [char]0x3068, [char]0x691c, [char]0x7d22, [char]0x30d0, [char]0x30fc))
        $jaSearchAlt = (-join @([char]0x30A2, [char]0x30C9, [char]0x30EC, [char]0x30B9, [char]0x691C, [char]0x7D22, [char]0x30D0, [char]0x30FC))
        if ($edit.Current.Name -notin @('Address and search bar', 'Address bar', $jaAddress, $jaSearch, $jaSearchAlt)) { continue }
        $vp = $null
        if (-not $edit.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$vp)) { continue }
        $value = [string]$vp.Current.Value
        foreach ($path in $paths) {
            if ($value -ceq ('github.com' + $path) -or $value -ceq ('https://github.com' + $path)) { return $true }
        }
    }
    return $false
}

function Get-PageNames($document) {
    foreach ($element in $document.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition
    )) {
        $name = $element.Current.Name
        if ($name) { Write-Output $name }
    }
}

function Find-BillingPage([string]$title, [string[]]$paths, [string]$requiredName, [long]$expectedHandle=0) {
    $docCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Document
    )
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        foreach ($p in @(Get-Process chrome -ErrorAction SilentlyContinue | Where-Object {$_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -eq ($title + ' - Google Chrome') -and ($expectedHandle -eq 0 -or [long]$_.MainWindowHandle -eq $expectedHandle)})) {
            try {
                $window = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
                if (-not (Test-BillingAddress $window $paths)) { continue }
                # Chrome may expose cached/background tabs as direct Window
                # children. Only the live content Pane in the selected window
                # is eligible; same-title background documents are excluded.
                $docs = @($window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $docCondition) | Where-Object {
                    $_.Current.Name -ceq $title -and
                    (-not $_.Current.IsOffscreen) -and
                    [System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($_).Current.ControlType -eq [System.Windows.Automation.ControlType]::Pane
                })
                if ($docs.Count -ne 1) { continue }
                $names = @(Get-PageNames $docs[0])
                if ($names -notcontains ('@' + $Account) -or $names -notcontains 'Your personal account' -or $names -notcontains $requiredName) { continue }
                if (-not (Test-BillingAddress $window $paths)) { continue }
                return [pscustomobject]@{Window=$window; Document=$docs[0]; Names=$names}
            } catch {
                # Window disappeared, was navigated, or UIA is unavailable.
                continue
            }
        }
        Start-Sleep -Milliseconds 550
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'BILLING_PAGE_OR_ACCOUNT_NOT_VERIFIED'
}

# A matching tab might be a stale previously opened Billing page. Refresh
# that exact Chrome window, then require a new active document runtime ID.
# No global keystrokes, alternate accounts, or navigation outside fixed URLs.
function Refresh-BillingPage($page, [string]$title, [string[]]$paths, [string]$requiredName) {
    $window = $page.Window
    $originalRuntimeId = ($page.Document.GetRuntimeId() -join ',')
    $jpReload = (-join @([char]0x518D, [char]0x8AAD, [char]0x307F, [char]0x8FBC, [char]0x307F))
    $labels = @('Reload this page', 'Reload', 'Reload page', $jpReload)
    $buttonCond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Button
    )
    $buttons = @($window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $buttonCond) | Where-Object {$_.Current.Name -cin $labels})
    if ($buttons.Count -ne 1 -or -not (Test-BillingAddress $window $paths)) { throw 'BILLING_RELOAD_CONTROL_NOT_VERIFIED' }
    $invoke = $null
    if (-not $buttons[0].TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$invoke)) { throw 'BILLING_RELOAD_UNAVAILABLE' }
    $handle = [long]$window.Current.NativeWindowHandle
    $invoke.Invoke()
    $docCond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Document
    )
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    do {
        try {
            if ($window.Current.Name -cne ($title + ' - Google Chrome') -or
                (-not (Test-BillingAddress $window $paths)) -or
                [long]$window.Current.NativeWindowHandle -ne $handle) {
                Start-Sleep -Milliseconds 400
                continue
            }
            $docs = @($window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $docCond) | Where-Object {
                $_.Current.Name -ceq $title -and -not $_.Current.IsOffscreen -and
                [System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($_).Current.ControlType -eq [System.Windows.Automation.ControlType]::Pane
            })
            if ($docs.Count -eq 1 -and ($docs[0].GetRuntimeId() -join ',') -cne $originalRuntimeId) {
                $names = @(Get-PageNames $docs[0])
                if ($names -contains ('@' + $Account) -and
                    $names -contains 'Your personal account' -and
                    $names -contains $requiredName -and
                    (Test-BillingAddress $window $paths)) {
                    return [pscustomobject]@{Window=$window; Document=$docs[0]; Names=$names}
                }
            }
        } catch {
            # Reload in flight or Chrome accessibility tree being replaced.
        }
        Start-Sleep -Milliseconds 400
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'BILLING_FRESH_RELOAD_NOT_VERIFIED'
}

function Find-UniqueMatch([string[]]$names, [string]$pattern) {
    $matches = @($names | Where-Object {$_ -cmatch $pattern} | Select-Object -Unique)
    if ($matches.Count -ne 1) { throw 'BILLING_EXPECTED_FIELD_MISSING_OR_AMBIGUOUS' }
    return [string]$matches[0]
}

function Find-PreviousAmount([string[]]$names, [string]$anchor) {
    $values = @()
    for ($i=1; $i -lt $names.Length; $i++) {
        if ($names[$i] -ceq $anchor -and $names[$i-1] -cmatch '^\$[0-9,]+(?:\.[0-9]{1,2})?$') { $values += $names[$i-1] }
    }
    $values = @($values | Select-Object -Unique)
    if ($values.Count -ne 1) { throw 'BILLING_AMOUNT_NOT_VERIFIED' }
    return [string]$values[0]
}

# A single process may interact with the authenticated UI at a time. No
# global keyboard injection, remote port, or arbitrary page/command input.
$mutex = New-Object System.Threading.Mutex($false, 'Local\KiNoTchDevflowBillingObserver')
$held = $false
try {
    try { $held = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) { throw 'BILLING_OBSERVER_BUSY' }
    $overviewPaths = @('/settings/billing', '/settings/billing/overview')
    Start-Process 'https://github.com/settings/billing'
    Start-Sleep -Milliseconds 1600
    $overview = Find-BillingPage 'Billing Overview' $overviewPaths 'Current metered usage'
    $overview = Refresh-BillingPage $overview 'Billing Overview' $overviewPaths 'Current metered usage'
    $buttonCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Button
    )
    $buttons = @($overview.Document.FindAll([System.Windows.Automation.TreeScope]::Descendants, $buttonCondition) | Where-Object {$_.Current.Name -ceq 'Actions'})
    if ($buttons.Count -ne 1 -or -not (Test-BillingAddress $overview.Window $overviewPaths)) { throw 'ACTIONS_PRODUCT_SELECTOR_NOT_VERIFIED' }
    $invoke = $null
    if (-not $buttons[0].TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$invoke)) { throw 'ACTIONS_SELECTOR_UNAVAILABLE' }
    $invoke.Invoke()
    $overview = Find-BillingPage 'Billing Overview' $overviewPaths 'Included compute usage' ([long]$overview.Window.Current.NativeWindowHandle)
    $names = [string[]]$overview.Names
    $period = Find-UniqueMatch $names '^Gross metered usage for [A-Za-z]+ 1 - [A-Za-z]+ [0-9]{1,2}, [0-9]{4}\.$'
    $discountPeriod = Find-UniqueMatch $names '^Included usage discounts for [A-Za-z]+ 1 - [A-Za-z]+ [0-9]{1,2}, [0-9]{4}\.$'
    $compute = Find-UniqueMatch $names '^\$[0-9,]+(?:\.[0-9]{1,2})? used / \$[0-9,]+(?:\.[0-9]{1,2})? included$'
    $storage = Find-UniqueMatch $names '^[0-9,.]+ GB used / [0-9,.]+ GB included$'
    $gross = Find-PreviousAmount $names $period
    $discount = Find-PreviousAmount $names $discountPeriod
    $consumed = Find-PreviousAmount $names 'consumed usage'
    $actionDiscount = Find-PreviousAmount $names 'discounts'
    $billable = Find-PreviousAmount $names 'Total billable usage after subtracting discounts from consumed usage'
    if (-not (Test-BillingAddress $overview.Window $overviewPaths)) { throw 'BILLING_OVERVIEW_NAVIGATED' }

    Start-Process 'https://github.com/settings/billing/budgets'
    Start-Sleep -Milliseconds 1600
    $budgets = Find-BillingPage 'Budgets' @('/settings/billing/budgets') 'Budget table'
    $budgets = Refresh-BillingPage $budgets 'Budgets' @('/settings/billing/budgets') 'Budget table'
    $names = [string[]]$budgets.Names
    # Exact account-scoped Actions row, never a neighboring SKU/repo row.
    $rowPattern = '^Account ' + [regex]::Escape($Account) + ' \p{P} Actions$'
    $indices = @()
    for($i=0; $i -lt $names.Length; $i++) {
        if ($names[$i] -cmatch $rowPattern) { $indices += $i }
    }
    if ($indices.Count -ne 1 -or $indices[0]+2 -ge $names.Length) { throw 'ACTIONS_ACCOUNT_BUDGET_ROW_NOT_VERIFIED' }
    $budgetAmount = $names[$indices[0]+1]
    $budgetState = $names[$indices[0]+2]
    if ($budgetAmount -cnotmatch '^\$[0-9,]+(?:\.[0-9]{1,2})? / \$[0-9,]+(?:\.[0-9]{1,2})? spent$' -or
        $budgetState -cnotmatch '^[0-9]+% of budget limit used [0-9]+%(?: Usage blocked)?$') {
        throw 'ACTIONS_BUDGET_LAYOUT_CHANGED'
    }
    if (-not (Test-BillingAddress $budgets.Window @('/settings/billing/budgets'))) { throw 'BUDGETS_PAGE_NAVIGATED' }
    # Only allowlisted strings, never DOM, page HTML, browser history or tokens.
    [ordered]@{
        account=$Account
        period=$period
        discount_period=$discountPeriod
        compute=$compute
        storage=$storage
        gross=$gross
        included_discount=$discount
        consumed=$consumed
        actions_discount=$actionDiscount
        billable=$billable
        budget_amount=$budgetAmount
        budget_state=$budgetState
    } | ConvertTo-Json -Compress
} catch {
    # No raw exception (which may contain machine paths/page text).
    $message = [string]$_.Exception.Message
    if ($message -cmatch '^[A-Z_]{8,80}$') {
        [Console]::Error.WriteLine($message)
    } else {
        [Console]::Error.WriteLine('BILLING_UI_OBSERVATION_FAILED')
    }
    exit 2
} finally {
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
