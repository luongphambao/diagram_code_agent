#!/usr/bin/env pwsh
# push.ps1 — stage code-only changes and push to GitHub.
# Usage:
#   .\push.ps1                    # prompts for commit message
#   .\push.ps1 "feat: add WBS"    # pass message directly
#
# .gitignore already excludes DATA/, generated outputs, temp scripts, etc.
# This script just makes the add → commit → push loop a single command.

param(
    [string]$Message = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "=== Code Push to GitHub ===" -ForegroundColor Cyan

# --- show current diff summary -------------------------------------------------
Write-Host ""
Write-Host "Changed files:" -ForegroundColor Yellow
git -C $root status --short

# --- require a commit message --------------------------------------------------
if ($Message -eq "") {
    Write-Host ""
    $Message = Read-Host "Commit message (empty to abort)"
}
if ($Message.Trim() -eq "") {
    Write-Host "Aborted: empty commit message." -ForegroundColor Red
    exit 1
}

# --- stage everything not excluded by .gitignore --------------------------------
git -C $root add -A

# show exactly what will be committed
$staged = git -C $root diff --cached --name-only
if (-not $staged) {
    Write-Host "Nothing to commit." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "Staged files:" -ForegroundColor Green
$staged | ForEach-Object { Write-Host "  $_" }

# --- confirm before committing -------------------------------------------------
Write-Host ""
$ok = Read-Host "Proceed with commit + push? [y/N]"
if ($ok -ne "y" -and $ok -ne "Y") {
    git -C $root restore --staged .
    Write-Host "Aborted. (staged changes were un-staged)" -ForegroundColor Yellow
    exit 1
}

# --- commit + push -------------------------------------------------------------
git -C $root commit -m $Message
git -C $root push origin HEAD

Write-Host ""
Write-Host "Pushed to GitHub ($((git -C $root rev-parse --abbrev-ref HEAD)))." -ForegroundColor Green
