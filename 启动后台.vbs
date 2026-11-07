Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
Set folder = fso.GetFolder(dir)
For Each f In folder.Files
  If LCase(fso.GetExtensionName(f.Name)) = "cmd" Then
    If InStr(f.Name, "bak") = 0 And InStr(f.Name, "egister") = 0 Then
      sh.Run "cmd /c \"" & f.Path & "\"", 0, False
      WScript.Quit
    End If
  End If
Next
