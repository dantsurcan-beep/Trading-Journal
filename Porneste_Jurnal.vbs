Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "G:\Contul meu Drive\TRADING\Trading Journal"
WshShell.Run "cmd /c for /f ""tokens=5"" %a in ('netstat -aon ^| findstr :850') do taskkill /F /PID %a", 0, True
WshShell.Run """G:\Contul meu Drive\TRADING\Trading Journal\.venv\Scripts\python.exe"" -m streamlit run app.py --server.port 8501", 0, False