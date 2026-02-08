' sxopen.vbs - Silent wrapper for sxopen.ps1
Set objShell = CreateObject("WScript.Shell")
Set args = WScript.Arguments

If args.Count > 0 Then
    strUrl = args(0)
    ' Get the directory where the VBS is located
    strDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
    strPS1 = strDir & "sxopen.ps1"
    
    ' Run PowerShell hidden
    strCommand = "powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & strPS1 & """ """ & strUrl & """"
    objShell.Run strCommand, 0, False
End If
