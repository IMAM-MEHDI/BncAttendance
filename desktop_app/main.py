import sys
import os
from PyQt6.QtWidgets import QApplication

# Add current directory to path so modules can be found
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.paths import get_resource_path

# Fix missing AI model dependencies by directing facenet_pytorch to bundled weights
os.environ["TORCH_HOME"] = get_resource_path(os.path.join("assets", "torch"))

from ui.main_window import MainWindow
from ui.login_window import LoginWindow
from database.session import init_db

import traceback
from PyQt6.QtWidgets import QMessageBox

def global_exception_hook(exctype, value, tb):
    """Catch unhandled exceptions and show them in a GUI dialog instead of silently crashing."""
    err_msg = "".join(traceback.format_exception(exctype, value, tb))
    with open("error_log.txt", "w") as f:
        f.write(err_msg)
    print(err_msg)
    # If QApplication is running, show a message box
    if QApplication.instance():
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Critical Error")
        msg.setText("The application encountered an unexpected error and needs to close.")
        msg.setDetailedText(err_msg)
        msg.exec()
    sys.__excepthook__(exctype, value, tb)
    sys.exit(1)

sys.excepthook = global_exception_hook

def main():
    print("Initializing Database...")
    try:
        init_db()
        from init_admin import initialize as init_admin_user
        init_admin_user() # Ensure default admin is created in SQLite
    except Exception as e:
        print(f"Warning: DB initialization error: {e}")

    app = QApplication(sys.argv)
    
    # Fix for Windows taskbar icon
    if os.name == 'nt':
        import ctypes
        myappid = 'bnc.attendance.ems.1.1.0' 
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    # Set Global App Icon
    from PyQt6.QtGui import QIcon
    icon_path = get_resource_path(os.path.join("assets", "logo.png"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # Start with Login
    login = LoginWindow()
    main_window = None

    def on_login_success(user_id):
        nonlocal main_window, login
        print(f"Login successful, loading dashboard...")
        login.hide()
        main_window = MainWindow(user_id)
        main_window.logout_signal.connect(on_logout)
        main_window.show()

    def on_logout():
        nonlocal main_window, login
        print("User logged out, returning to login screen...")
        login = LoginWindow()
        login.login_success.connect(on_login_success)
        login.show()

    login.login_success.connect(on_login_success)
    login.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
