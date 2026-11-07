import sys
import os
from streamlit.web import cli as stcli

if __name__ == '__main__':
    # Setează calea către app.py în mod dinamic pentru executabil
    if getattr(sys, 'frozen', False):
        # Dacă rulați ca executabil împachetat de PyInstaller
        application_path = sys._MEIPASS
    else:
        application_path = os.path.dirname(os.path.abspath(__file__))
    
    app_path = os.path.join(application_path, 'app.py')
    
    # Parametrii cu care va porni Streamlit
    sys.argv = [
        "streamlit",
        "run",
        app_path,
        "--global.developmentMode=false",
        "--server.headless=true",
        "--browser.gatherUsageStats=false"
    ]
    
    # Pornește serverul Streamlit și deschide browserul automat
    import webbrowser
    from threading import Timer
    
    def open_browser():
        webbrowser.open_new("http://localhost:8501")

    Timer(1.5, open_browser).start()
    stcli.main()