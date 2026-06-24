<#
.SYNOPSIS
Regenerate the `poc_studio_project_structure.txt` file for the POC_STUDIO project.

.PARAMETER OutFile
Output filename to write the project structure to. Defaults to `poc_studio_project_structure.txt`.
#>
param(
  [string]$OutFile = "poc_studio_project_structure.txt"
)

Write-Host "Generating project structure into $OutFile" -ForegroundColor Cyan
Get-ChildItem -Recurse -Force | Sort-Object FullName | ForEach-Object {
  $relative = $_.FullName.Replace((Get-Location).Path + '\\','')
  if ($_.PSIsContainer) { "- $relative/" } else { "- $relative" }
} | Out-File -Encoding utf8 $OutFile

Write-Host "Wrote $OutFile" -ForegroundColor Green
