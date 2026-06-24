Set WshShell = CreateObject("WScript.Shell")

' Define absolute paths
Dim basePath
basePath = "C:\Users\cread\VSCode_Projects\POC_STUDIO"

' Use pythonw.exe (Windowed) to guarantee no terminal window appears
WshShell.Run basePath & "\.venv\Scripts\pythonw.exe " & basePath & "\src\studio_app.py", 0

Set WshShell = Nothing