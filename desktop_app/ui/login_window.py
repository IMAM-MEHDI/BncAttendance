import sys
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLineEdit, QPushButton, 
                             QLabel, QMessageBox, QHBoxLayout, QFrame)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont, QIcon

from database.session import SessionLocal
from database import crud

class LoginWindow(QWidget):
    login_success = pyqtSignal(object) # Emits the user object on success

    def __init__(self):
        super().__init__()
        self.setWindowTitle("BNC Attendance System - Login")
        self.setFixedSize(400, 500)
        self.db = SessionLocal()
        self.setup_ui()

    def setup_ui(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #0f172a;
                font-family: 'Inter', 'Segoe UI', Arial;
            }
            QMessageBox QLabel { color: #000000; }
            QLabel#Title {
                font-size: 36px;
                font-weight: 800;
                color: #38bdf8;
                margin-top: 20px;
            }
            QLabel#Subtitle {
                font-size: 14px;
                color: #94a3b8;
                margin-bottom: 20px;
            }
            QLineEdit {
                padding: 15px;
                border: 1px solid #334155;
                border-radius: 12px;
                background-color: #1e293b;
                color: #f1f5f9;
                font-size: 15px;
            }
            QLineEdit:focus {
                border: 1px solid #38bdf8;
            }
            QPushButton {
                background-color: #38bdf8;
                color: #0f172a;
                font-weight: 800;
                border-radius: 12px;
                font-size: 15px;
                border: none;
                min-height: 55px;
                margin-top: 10px;
            }
            QPushButton:hover {
                background-color: #7dd3fc;
            }
            QPushButton:pressed {
                background-color: #0ea5e9;
            }
        """)
        layout = QVBoxLayout()
        layout.setContentsMargins(50, 50, 50, 50)
        layout.setSpacing(15)

        # Logo/Title
        title = QLabel("BNC EMS")
        title.setObjectName("Title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Education Management Portal")
        subtitle.setObjectName("Subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        
        layout.addSpacing(20)

        # Inputs
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Enrollment ID / Admin ID")
        layout.addWidget(self.user_input)

        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("Password")
        self.pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.pass_input)

        # Login Button
        self.login_btn = QPushButton("SIGN IN")
        self.login_btn.clicked.connect(self.handle_login)
        layout.addWidget(self.login_btn)

        layout.addStretch()
        self.setLayout(layout)

    def handle_login(self):
        user_id = self.user_input.text().strip()
        password = self.pass_input.text().strip()

        if not user_id or not password:
            QMessageBox.warning(self, "Error", "Please fill in all fields.")
            return

        user = crud.get_user_by_enrollment(self.db, user_id)
        if user and crud.verify_password(password, user.password_hash):
            if user.role in ['admin', 'teacher', 'hod']:
                u_id = user.id # Get primary key
                self.db.close() # Close immediately
                self.login_success.emit(u_id)
                self.close()
            else:
                QMessageBox.critical(self, "Access Denied", "Students do not have portal access.")
        else:
            QMessageBox.critical(self, "Error", "Invalid ID or Password.")

    def closeEvent(self, event):
        self.db.close()
        event.accept()
