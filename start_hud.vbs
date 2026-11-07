Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
Base = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = Base
Exe = Base & "\dist\PokerHelperV2\PokerHelperV2.exe"
If FSO.FileExists(Exe) Then
    WshShell.Run Chr(34) & Exe & Chr(34), 1, False
Else
    WshShell.Run "pythonw " & Chr(34) & Base & "\main_hud.py" & Chr(34), 0, False
End If
