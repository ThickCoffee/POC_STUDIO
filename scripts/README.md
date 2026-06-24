Update scripts

This folder contains a helper PowerShell script to regenerate the project structure file.

Files:
- `update_structure.ps1`: Regenerates `poc_studio_project_structure.txt` (default) or a specified output file.

Usage:
```powershell
# From the POC_STUDIO project root
.\scripts\update_structure.ps1
# Or with a custom filename
.\scripts\update_structure.ps1 -OutFile latest_structure.txt
```

Run this whenever you add/remove files to refresh `poc_studio_project_structure.txt`.
