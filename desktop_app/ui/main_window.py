import sys
import os
import cv2
import numpy as np
import uuid
import time
import threading
from datetime import datetime
from PyQt6 import sip
from PyQt6.QtWidgets import (QMainWindow, QLabel, QVBoxLayout, QWidget, QPushButton, 
                             QMessageBox, QTabWidget, QLineEdit, QFormLayout, QHBoxLayout,
                             QStackedWidget, QTableWidget, QTableWidgetItem, QComboBox,
                             QScrollArea, QFrame, QMenuBar, QMenu, QStatusBar, QToolBar,
                             QHeaderView)
from PyQt6.QtCore import pyqtSignal, QThread, Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap, QFont, QIcon, QAction

from recognition.engine import FaceRecognitionEngine
from database.session import SessionLocal
from database import crud, models
from sync import client as sync_client
from utils.reports import generate_pdf_report
from utils.version_check import get_latest_version_info, is_update_available
from utils.paths import get_resource_path
from utils.config import settings

class VersionCheckThread(QThread):
    finished_signal = pyqtSignal(dict) # Returns info if update available, else empty dict
    
    def run(self):
        try:
            info = get_latest_version_info()
            if is_update_available(info):
                self.finished_signal.emit(info)
            else:
                self.finished_signal.emit({})
        except Exception:
            self.finished_signal.emit({"error": "Failed to check for updates."})

class SyncThread(QThread):
    finished_signal = pyqtSignal(str)
    def run(self):
        try:
            count = sync_client.sync_data()
            if count > 0:
                self.finished_signal.emit(f"Successfully synced {count} records.")
            else:
                self.finished_signal.emit("All records are already in the cloud.")
        except Exception as e:
            self.finished_signal.emit(f"Sync failed: {str(e)}")

class PullMasterDataThread(QThread):
    finished_signal = pyqtSignal(dict)
    def __init__(self, enrollment, password):
        super().__init__()
        self.enrollment = enrollment
        self.password = password
        
    def run(self):
        try:
            from sync.client import pull_master_data_from_backend
            res = pull_master_data_from_backend(self.enrollment, self.password)
            self.finished_signal.emit(res)
        except Exception as e:
            self.finished_signal.emit({"status": "error", "message": str(e)})

class PushMasterDataThread(QThread):
    finished_signal = pyqtSignal(dict)
    def __init__(self, enrollment, password):
        super().__init__()
        self.enrollment = enrollment
        self.password = password
        
    def run(self):
        try:
            from sync.client import push_master_data_to_backend
            res = push_master_data_to_backend(self.enrollment, self.password)
            self.finished_signal.emit(res)
        except Exception as e:
            self.finished_signal.emit({"status": "error", "message": str(e)})

class VideoThread(QThread):
    change_pixmap_signal = pyqtSignal(np.ndarray)
    face_detected_signal = pyqtSignal(object, object, bool)

    def __init__(self, engine, cam_index=0):
        super().__init__()
        self.engine = engine
        self.cam_index = cam_index
        self._run_flag = True

    def run(self):
        cap = cv2.VideoCapture(self.cam_index, cv2.CAP_DSHOW)
        while self._run_flag:
            ret, cv_img = cap.read()
            if ret:
                self.current_cv_img = cv_img.copy() # Store for monitor
                rgb_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                embedding, box, is_live = self.engine.detect_and_embed(rgb_img, check_liveness=True)
                
                if box is not None:
                    x1, y1, x2, y2 = [int(b) for b in box]
                    color = (0, 255, 0) if is_live else (0, 165, 255)
                    cv2.rectangle(cv_img, (x1, y1), (x2, y2), color, 2)
                    text = "Live Face" if is_live else "Blink to verify..."
                    cv2.putText(cv_img, text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                    self.face_detected_signal.emit(embedding, box, is_live)
                else:
                    self.face_detected_signal.emit(None, None, False)
                self.change_pixmap_signal.emit(cv_img)
        cap.release()

    def stop(self):
        self._run_flag = False
        self.wait()

class MainWindow(QMainWindow):
    logout_signal = pyqtSignal()
    
    def __init__(self, user_id):
        super().__init__()
        self.db = SessionLocal()
        try:
            self.db.rollback()
            # Fetch user freshly to ensure session attachment
            from database import models
            self.current_user = self.db.query(models.User).filter(models.User.id == user_id).first()
        except Exception as e:
            self.db.rollback()
            print(f"Startup DB Error: {e}")
            
        self.setWindowTitle(f"BNC EMS - Logged in as {self.current_user.name} ({self.current_user.role.upper()})")
        self.resize(1200, 900)
        self.setMinimumSize(900, 620)   # Ensures layout works on smaller monitors
        
        # Set App Icon
        icon_path = get_resource_path(os.path.join("assets", "logo.png"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        print("Initializing Engine...")
        self.engine = FaceRecognitionEngine()
        # Cloud sync credentials — pre-loaded from .env so no manual prompt needed
        self.session_cloud_pw = settings.CLOUD_ADMIN_PASSWORD or None
        self.session_cloud_enrollment = settings.CLOUD_ADMIN_ENROLLMENT or "admin"
        self.active_session = None # For Teachers: {paper_name, paper_code, semester}
        self.current_embedding = None
        self.is_live = False
        self.last_mark_time = 0
        self.auto_mark_delay = settings.KIOSK.get("auto_mark_delay", 10)
        
        # String Constants to fix lints
        self.STR_SEM = "Semester:"
        self.STR_EXP_ERR = "Export Error"
        # Improved dialog style with high contrast
        self.STR_DIALOG_STYLE = """
            QDialog {
                background-color: #f8fafc;
            }
            QLabel {
                color: #1e293b;
                font-weight: 500;
            }
            QLineEdit, QComboBox, QTimeEdit {
                color: #0f172a;
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 8px;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #1e293b;
                selection-background-color: #0ea5e9;
                selection-color: #ffffff;
            }
            QPushButton {
                background-color: #e2e8f0;
                color: #1e293b;
                border-radius: 6px;
                font-weight: 600;
                padding: 9px 18px;
                border: none;
            }
            QPushButton:hover {
                background-color: #cbd5e1;
            }
            QPushButton#PrimaryBtn {
                background-color: #0ea5e9;
                color: #ffffff;
                border-radius: 6px;
                font-weight: 600;
                padding: 10px;
            }
            QPushButton#PrimaryBtn:hover {
                background-color: #38bdf8;
            }
        """

        print("Setting up UI...")
        self.init_standard_ui()
        self.setup_ui()
        print("UI Setup Complete.")
        
        # Threads
        print("Initializing Video Thread (Paused)...")
        self.cam_index = settings.KIOSK.get("default_camera_index", 0)
        self.thread = VideoThread(self.engine, self.cam_index)
        self.thread.change_pixmap_signal.connect(self.update_image)
        self.thread.face_detected_signal.connect(self.update_face_status)
        # self.thread.start() # Removed autostart - camera default is OFF
        print("Startup sequence finished.")

        # Version Check (Manual)
        self.version_thread = VersionCheckThread()
        self.version_thread.finished_signal.connect(self.handle_version_result)

        # Background Sync (configured)
        self.sync_thread = SyncThread()
        self.sync_thread.finished_signal.connect(self.handle_sync_result)
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.run_sync)
        self.sync_timer.start(settings.SYNC.get("timer_interval_ms", 300000))

    def setup_ui(self):
        # Global Stylesheet
        t = settings.THEME
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: #0f172a;
            }}
            QMenuBar {{
                background-color: #0f172a;
                color: #f8fafc;
                border-bottom: 1px solid #1e293b;
            }}
            QMenuBar::item:selected {{
                background-color: #1e293b;
            }}
            QToolBar {{
                background-color: #0f172a;
                border-bottom: 1px solid #1e293b;
                padding: 8px;
            }}
            QToolButton {{
                color: #ffffff;
                font-weight: bold;
                padding: 5px 10px;
            }}
            QFrame#Sidebar {{
                background-color: #1e293b;
                border-right: 1px solid #334155;
            }}
            QLabel#Logo {{
                color: #38bdf8;
                font-size: 24px;
                font-weight: 800;
                margin-bottom: 5px;
            }}
            QPushButton#NavBtn {{
                background-color: transparent;
                color: #94a3b8;
                text-align: left;
                padding: 12px 20px;
                border: none;
                font-size: 14px;
                font-weight: 500;
                border-radius: 8px;
                margin: 4px 12px;
            }}
            QPushButton#NavBtn:hover {{
                background-color: #1e293b;
                color: #f8fafc;
            }}
            QPushButton#NavBtn[active="true"] {{
                background-color: #0ea5e9;
                color: #ffffff;
                font-weight: 600;
            }}
            
            /* Card System */
            QFrame#MainCard {{
                background-color: #1e293b;
                border-radius: 20px;
                border: 1px solid #334155;
            }}
            
            QTabWidget::pane {{
                border: 1px solid #334155;
                background: #1e293b;
                border-radius: 12px;
            }}
            QTabBar::tab {{
                background: #0f172a;
                color: #94a3b8;
                padding: 12px 25px;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                margin-right: 4px;
            }}
            QTabBar::tab:selected {{
                background: #1e293b;
                color: #38bdf8;
            }}

            /* Buttons */
            QPushButton#PrimaryBtn {{
                background-color: #38bdf8;
                color: #0f172a;
                border-radius: 12px;
                padding: 12px 20px;
                font-weight: 800;
                font-size: 14px;
                border: none;
            }}
            QPushButton#PrimaryBtn:hover {{ background-color: #7dd3fc; }}
            
            QPushButton#SuccessBtn {{
                background-color: #10b981;
                color: #000000;
                border-radius: 12px;
                padding: 12px;
                font-weight: 800;
                border: none;
            }}
            QPushButton#SuccessBtn:hover {{ background-color: #34d399; }}

            QPushButton#DangerBtn {{
                background-color: #ef4444;
                color: #ffffff;
                border-radius: 12px;
                padding: 12px;
                font-weight: 800;
                border: none;
            }}
            QPushButton#DangerBtn:hover {{ background-color: #f87171; }}

            /* Inputs */
            QLineEdit, QComboBox {{
                background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 10px;
                color: #f1f5f9;
                font-size: 13px;
            }}
            QLineEdit:focus {{ border: 1px solid #38bdf8; }}

            /* Tables */
            QTableWidget {{
                background-color: #1e293b;
                alternate-background-color: #1a2233;
                gridline-color: #334155;
                color: #f1f5f9;
                border-radius: 15px;
                border: 1px solid #334155;
            }}
            QHeaderView::section {{
                background-color: #0f172a;
                color: #94a3b8;
                padding: 12px;
                border: none;
                font-weight: bold;
            }}
            
            QScrollBar:vertical {{
                border: none;
                background: #0f172a;
                width: 10px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background: #334155;
                min-height: 30px;
                border-radius: 5px;
            }}
            
            QLabel {{ color: #f8fafc; }}
            QMessageBox QLabel {{ color: #0f172a; }}
            QScrollArea {{ border: none; background: transparent; }}

            /* High Contrast for Admin Inputs */
            QLineEdit#AdminInput {{
                background-color: #ffffff;
                color: #0f172a;
                border: 2px solid #38bdf8;
            }}

            /* ── ComboBox dropdown list (dark theme) ─────────────────── */
            QComboBox QAbstractItemView {{
                background-color: #1e293b;
                color: #f1f5f9;
                selection-background-color: #0ea5e9;
                selection-color: #ffffff;
                border: 1px solid #334155;
                outline: none;
            }}

            /* ── Light-panel override (white-bg forms) ───────────────── */
            /* Applied via setObjectName('LightPanel') on each white container */
            QWidget#LightPanel, QFrame#LightPanel {{
                background-color: #ffffff;
                border-radius: 12px;
                border: 1px solid #dcdde1;
            }}
            QWidget#LightPanel QLabel, QFrame#LightPanel QLabel {{
                color: #1e293b;
            }}
            QWidget#LightPanel QLineEdit, QFrame#LightPanel QLineEdit {{
                background-color: #f8fafc;
                color: #1e293b;
                border: 1px solid #cbd5e1;
            }}
            QWidget#LightPanel QComboBox, QFrame#LightPanel QComboBox {{
                background-color: #f8fafc;
                color: #1e293b;
                border: 1px solid #cbd5e1;
            }}
            QWidget#LightPanel QComboBox QAbstractItemView,
            QFrame#LightPanel QComboBox QAbstractItemView {{
                background-color: #ffffff;
                color: #1e293b;
                selection-background-color: #0ea5e9;
                selection-color: #ffffff;
            }}
        """)

        # ── Application-level popup/dialog styles ───────────────────────────
        # QMessageBox, QInputDialog, and other top-level system dialogs are NOT
        # children of MainWindow, so they ignore self.setStyleSheet().  They
        # must be styled via QApplication to guarantee readable text.
        from PyQt6.QtWidgets import QApplication
        _popup_style = """
            QMessageBox {
                background-color: #f8fafc;
            }
            QMessageBox QLabel {
                color: #1e293b;
                font-size: 13px;
                font-weight: 500;
            }
            QMessageBox QPushButton {
                background-color: #0ea5e9;
                color: #ffffff;
                border-radius: 6px;
                padding: 8px 22px;
                font-weight: 600;
                min-width: 80px;
                border: none;
            }
            QMessageBox QPushButton:hover {
                background-color: #38bdf8;
            }
            QMessageBox QPushButton:pressed {
                background-color: #0284c7;
            }
            QInputDialog {
                background-color: #f8fafc;
            }
            QInputDialog QLabel {
                color: #1e293b;
                font-size: 13px;
                font-weight: 500;
            }
            QInputDialog QLineEdit {
                background-color: #ffffff;
                color: #1e293b;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 8px;
            }
            QInputDialog QPushButton {
                background-color: #0ea5e9;
                color: #ffffff;
                border-radius: 6px;
                padding: 8px 22px;
                font-weight: 600;
                min-width: 80px;
                border: none;
            }
            QInputDialog QPushButton:hover {
                background-color: #38bdf8;
            }
        """
        app_inst = QApplication.instance()
        if app_inst:
            # Merge with any existing app-level stylesheet
            existing = app_inst.styleSheet()
            app_inst.setStyleSheet(existing + _popup_style)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        main_widget = QWidget()
        main_widget.setLayout(layout)
        self.setCentralWidget(main_widget)

        # 1. Sidebar
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setMinimumWidth(220)
        sidebar.setMaximumWidth(280)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 20, 0, 20)
        
        logo_container = QWidget()
        logo_layout = QVBoxLayout(logo_container)
        
        logo_img = QLabel()
        logo_path = get_resource_path(os.path.join("assets", "logo.png"))
        if os.path.exists(logo_path):
            pix = QPixmap(logo_path).scaled(60, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo_img.setPixmap(pix)
        logo_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_layout.addWidget(logo_img)
        
        logo_label = QLabel("BNC ATTENDANCE")
        logo_label.setObjectName("Logo")
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_layout.addWidget(logo_label)
        
        role_badge = QLabel(self.current_user.role.upper())
        role_badge.setStyleSheet("color: #38bdf8; font-size: 10px; font-weight: 800; background: #0f172a; padding: 4px 10px; border-radius: 10px;")
        role_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_layout.addWidget(role_badge)
        
        sidebar_layout.addWidget(logo_container)
        sidebar_layout.addSpacing(30)

        self.nav_buttons = {}
        self.NAV_KIOSK = "Attendance Kiosk"
        
        if self.current_user.role != 'admin':
            self.add_nav_item(sidebar_layout, self.NAV_KIOSK, "btn_kiosk")
        
        if self.current_user.role == 'admin':
            self.add_nav_item(sidebar_layout, "Admin Panel", "btn_admin")
        elif self.current_user.role == 'hod':
            self.add_nav_item(sidebar_layout, "HOD Panel", "btn_hod")
        elif self.current_user.role == 'teacher':
            self.add_nav_item(sidebar_layout, "Teacher Panel", "btn_teacher")

        sidebar_layout.addStretch()
        
        self.btn_check_updates = QPushButton(" Check for Updates")
        self.btn_check_updates.setObjectName("NavBtn")
        self.btn_check_updates.clicked.connect(self.check_for_updates_manually)
        sidebar_layout.addWidget(self.btn_check_updates)

        logout_btn = QPushButton(" Logout")
        logout_btn.setObjectName("NavBtn")
        logout_btn.clicked.connect(self.handle_logout)
        sidebar_layout.addWidget(logout_btn)

        layout.addWidget(sidebar)

        # 2. Content Area
        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Banner / Header Image
        banner_label = QLabel()
        banner_path = get_resource_path(os.path.join("assets", "banner.png"))
        if os.path.exists(banner_path):
            banner_label.setMaximumHeight(150)
            banner_label.setMinimumHeight(60)
            banner_label.setScaledContents(True)
            banner_pix = QPixmap(banner_path)
            banner_label.setPixmap(banner_pix)
        content_layout.addWidget(banner_label)

        # Main Workspace
        workspace_container = QWidget()
        workspace_layout = QVBoxLayout(workspace_container)
        workspace_layout.setContentsMargins(30, 30, 30, 30)

        self.stack = QStackedWidget()
        workspace_layout.addWidget(self.stack)
        content_layout.addWidget(workspace_container)

        # Footer
        footer = QFrame()
        footer.setFixedHeight(40)
        footer.setStyleSheet(f"background-color: {t['midnight']}; border-top: 1px solid {t['border_slate']};")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 0, 20, 0)
        
        footer_text = QLabel("© 2026 BNC Attendance System | Version 1.1.0 | All Rights Reserved")
        footer_text.setObjectName("FooterText")
        footer_layout.addWidget(footer_text)
        footer_layout.addStretch()
        
        status_indicator = QLabel("● System Ready")
        status_indicator.setStyleSheet("color: #10b981; font-size: 11px; font-weight: bold;")
        self.status_indicator = status_indicator # Save reference
        footer_layout.addWidget(status_indicator)
        
        content_layout.addWidget(footer)
        layout.addWidget(content_container)
        
        # Panels
        if self.current_user.role != 'admin':
            self.setup_kiosk_panel()
            
        if self.current_user.role == 'admin': self.setup_admin_panel()
        if self.current_user.role == 'hod': self.setup_hod_panel()
        if self.current_user.role == 'teacher': self.setup_teacher_panel()
        
        # Default View
        if self.current_user.role == 'admin':
            self.switch_panel("Admin Panel")
        else:
            self.switch_panel(self.NAV_KIOSK)

    def init_standard_ui(self):
        # Menu Bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        edit_menu = menubar.addMenu("&Edit")
        view_menu = menubar.addMenu("&View")
        help_menu = menubar.addMenu("&Help")

        exit_action = QAction("&Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.setStatusTip("Exit Application")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        about_action = QAction("&About", self)
        about_action.triggered.connect(lambda: QMessageBox.about(self, "About BNC Attendance", "BNC Biometric Attendance System\nVersion 1.1.0\nDeveloped for Enterprise Scale."))
        help_menu.addAction(about_action)

        # Tool Bar
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)
        
        sync_action = QAction(" Sync Now", self)
        sync_action.setStatusTip("Manually Sync Data with Server")
        sync_action.triggered.connect(self.run_sync)
        toolbar.addAction(sync_action)
        
        update_action = QAction(" Check Updates", self)
        update_action.triggered.connect(self.check_for_updates_manually)
        toolbar.addAction(update_action)

        # Status Bar
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Ready")

    def add_nav_item(self, layout, text, attr_name):
        btn = QPushButton(f"  {text}")
        btn.setObjectName("NavBtn")
        btn.setToolTip(f"Switch to {text}") # Interaction: Tooltip
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        setattr(self, attr_name, btn)
        btn.clicked.connect(lambda: self.switch_panel(text))
        layout.addWidget(btn)
        self.nav_buttons[text] = btn

    def show_notification(self, message, is_error=False):
        """Interaction: Notification System"""
        color = "#ef4444" if is_error else "#10b981"
        self.status_indicator.setText(f"● {message}")
        self.status_indicator.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold;")
        self.statusBar().showMessage(message, 5000)
        if is_error:
            print(f"NOTIFICATION ERROR: {message}")

    def _update_kiosk_face_status(self):
        """Keep the Student Enrollment face-ready indicator current."""
        if not hasattr(self, 'kiosk_face_status'):
            return
        face_ready = (
            getattr(self, 'current_embedding', None) is not None
            and getattr(self, 'is_live', False)
        )
        if face_ready:
            self.kiosk_face_status.setText("✅  Face captured and live — fill in the form and click Register Student")
            self.kiosk_face_status.setStyleSheet(
                "background: #14532d; color: #86efac; font-weight: bold; font-size: 12px; "
                "padding: 10px; border-radius: 8px; margin-bottom: 8px;"
            )
        else:
            self.kiosk_face_status.setText(
                "⚠️  No face detected — go to 'Live Recognition' tab, turn on the camera and have the student look into it"
            )
            self.kiosk_face_status.setStyleSheet(
                "background: #7f1d1d; color: #fca5a5; font-weight: bold; font-size: 12px; "
                "padding: 10px; border-radius: 8px; margin-bottom: 8px;"
            )

    def switch_panel(self, text):
        if sip.isdeleted(self) or not hasattr(self, 'stack') or sip.isdeleted(self.stack):
            return
            
        # Reset nav buttons
        for btn in self.nav_buttons.values():
            if not sip.isdeleted(btn):
                btn.setProperty("active", False)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
        
        target_btn = self.nav_buttons.get(text)
        if target_btn and not sip.isdeleted(target_btn):
            target_btn.setProperty("active", True)
            target_btn.style().unpolish(target_btn)
            target_btn.style().polish(target_btn)

        if text == self.NAV_KIOSK and not sip.isdeleted(self.kiosk_panel): 
            self.stack.setCurrentWidget(self.kiosk_panel)
        elif text == "Admin Panel" and hasattr(self, 'admin_panel') and not sip.isdeleted(self.admin_panel): 
            self.stack.setCurrentWidget(self.admin_panel)
        elif text == "HOD Panel" and hasattr(self, 'hod_panel') and not sip.isdeleted(self.hod_panel): 
            self.stack.setCurrentWidget(self.hod_panel)
        elif text == "Teacher Panel" and hasattr(self, 'teacher_panel') and not sip.isdeleted(self.teacher_panel): 
            self.stack.setCurrentWidget(self.teacher_panel)

    def create_camera_control_tab(self):
        tab = QWidget()
        layout = QFormLayout(tab)
        self.cam_toggle = QPushButton("TURN CAMERA ON")
        self.cam_toggle.setObjectName("PrimaryBtn")
        self.cam_toggle.clicked.connect(self.toggle_camera)
        self.cam_select = QComboBox()
        self.cam_select.addItems(["Camera 0 (Default)", "Camera 1", "Camera 2"])
        self.cam_select.currentIndexChanged.connect(self.change_camera_index)
        layout.addRow("Camera Power:", self.cam_toggle)
        layout.addRow("Select Device:", self.cam_select)
        return tab

    # --- Kiosk Panel ---
    def setup_kiosk_panel(self):
        self.kiosk_panel = QWidget()
        layout = QVBoxLayout(self.kiosk_panel)
        
        tabs = QTabWidget()
        
        # Camera Tab
        cam_tab = QWidget()
        cam_layout = QVBoxLayout(cam_tab)
        
        # Camera Controls
        cam_controls = QFrame()
        cam_controls.setObjectName("LightPanel")
        cam_ctrl_layout = QHBoxLayout(cam_controls)
        
        self.kiosk_cam_toggle = QPushButton("TURN CAMERA ON")
        self.kiosk_cam_toggle.setObjectName("PrimaryBtn")
        self.kiosk_cam_toggle.clicked.connect(self.toggle_camera)
        
        self.kiosk_cam_select = QComboBox()
        self.kiosk_cam_select.addItems(["Camera 0 (Default)", "Camera 1", "Camera 2"])
        self.kiosk_cam_select.currentIndexChanged.connect(self.change_camera_index)
        
        cam_ctrl_layout.addWidget(QLabel("Camera Power:"))
        cam_ctrl_layout.addWidget(self.kiosk_cam_toggle)
        cam_ctrl_layout.addWidget(QLabel("Select Device:"))
        cam_ctrl_layout.addWidget(self.kiosk_cam_select)
        
        cam_layout.addWidget(cam_controls)
        
        self.image_label = QLabel()
        self.image_label.setMinimumSize(320, 240)
        self.image_label.setSizePolicy(
            self.image_label.sizePolicy().horizontalPolicy(),
            self.image_label.sizePolicy().verticalPolicy()
        )
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("border-radius: 15px; background: #0f172a; border: 1px solid #334155;")
        cam_layout.addWidget(self.image_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.status_label = QLabel("Waiting for Face...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #e2e8f0;")
        cam_layout.addWidget(self.status_label)
        
        tabs.addTab(cam_tab, "Live Recognition")
        
        # Registration Tab
        reg_tab = QWidget(); r_layout = QVBoxLayout(reg_tab)
        
        # Face capture status indicator
        self.kiosk_face_status = QLabel("⚠️  No face detected — go to 'Live Recognition' tab, turn on camera and look into it")
        self.kiosk_face_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.kiosk_face_status.setWordWrap(True)
        self.kiosk_face_status.setStyleSheet(
            "background: #7f1d1d; color: #fca5a5; font-weight: bold; font-size: 12px; "
            "padding: 10px; border-radius: 8px; margin-bottom: 8px;"
        )
        r_layout.addWidget(self.kiosk_face_status)
        
        reg_card = QWidget()
        reg_card.setObjectName("LightPanel")
        reg_card.setStyleSheet("padding: 20px;")
        rc_layout = QFormLayout(reg_card)
        self.stu_name = QLineEdit(); self.stu_enroll = QLineEdit(); self.stu_sem = QLineEdit(); self.stu_course = QLineEdit(); self.stu_major = QLineEdit()
        rc_layout.addRow("Student Name:", self.stu_name); rc_layout.addRow("Enrollment ID:", self.stu_enroll)
        rc_layout.addRow(self.STR_SEM, self.stu_sem); rc_layout.addRow("Course:", self.stu_course); rc_layout.addRow("Major/Minor:", self.stu_major)
        btn_enroll = QPushButton("Register Student"); btn_enroll.setObjectName("PrimaryBtn"); btn_enroll.clicked.connect(self.enroll_student)
        rc_layout.addRow(btn_enroll)
        r_layout.addWidget(reg_card); r_layout.addStretch()
        
        # Timer to keep the face-status indicator in sync
        face_status_timer = QTimer(self)
        face_status_timer.setInterval(1000)
        face_status_timer.timeout.connect(self._update_kiosk_face_status)
        face_status_timer.start()
        
        tabs.addTab(reg_tab, "Student Enrollment")
        
        layout.addWidget(tabs)
        self.stack.addWidget(self.kiosk_panel)

    # --- Admin Panel ---
    def create_reports_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        
        # Filters
        filter_frame = QFrame()
        filter_frame.setObjectName("LightPanel")
        filter_frame.setStyleSheet("padding: 15px;")
        f_layout = QHBoxLayout(filter_frame)
        self.r_period = QComboBox(); self.r_period.addItems(["Daily", "Weekly", "Monthly"])
        self.r_period.setToolTip("Select report time range")
        
        self.r_sem = QComboBox(); self.r_sem.addItems(["All Semesters", "1", "2", "3", "4", "5", "6", "7", "8"])
        self.r_sem.setToolTip("Filter by Student Semester")
        
        self.r_paper = QComboBox(); self.r_paper.addItem("All Papers")
        self.r_paper.setToolTip("Filter by specific Subject/Paper")
        btn_refresh = QPushButton("Generate Report"); btn_refresh.setObjectName("PrimaryBtn")
        btn_refresh.clicked.connect(self.refresh_reports)
        btn_export_analytics = QPushButton("Export PDF"); btn_export_analytics.setObjectName("SuccessBtn")
        btn_export_analytics.clicked.connect(self.export_analytics_pdf)
        f_layout.addWidget(QLabel("Period:")); f_layout.addWidget(self.r_period)
        f_layout.addWidget(QLabel(self.STR_SEM)); f_layout.addWidget(self.r_sem)
        f_layout.addWidget(QLabel("Paper:")); f_layout.addWidget(self.r_paper)
        f_layout.addWidget(btn_refresh); f_layout.addWidget(btn_export_analytics)
        layout.addWidget(filter_frame)
        
        # Status Label
        self.r_status_label = QLabel("Click 'Generate' to view records")
        self.r_status_label.setStyleSheet("color: #94a3b8; font-weight: bold; margin-top: 10px;")
        layout.addWidget(self.r_status_label)

        # Results Table
        self.report_table = QTableWidget(0, 4)
        self.report_table.setHorizontalHeaderLabels(["Date", "Enrollment", "Name", "Paper"])
        layout.addWidget(self.report_table)
        
        return tab

    def setup_admin_panel(self):
        self.admin_panel = QWidget()
        layout = QVBoxLayout(self.admin_panel)
        tabs = QTabWidget()
        def wrap_scroll(w):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(w)
            return scroll

        # Dept Management
        dept_tab = QWidget()
        d_layout = QVBoxLayout(dept_tab)
        self.dept_table = QTableWidget(0, 2)
        self.dept_table.setHorizontalHeaderLabels(["ID", "Department Name"])
        d_layout.addWidget(self.dept_table)
        btn_add_dept = QPushButton("Add Department"); btn_add_dept.setObjectName("PrimaryBtn"); btn_add_dept.clicked.connect(self.add_department_dialog)
        btn_del_dept = QPushButton("Delete Selected Dept"); btn_del_dept.setObjectName("DangerBtn"); btn_del_dept.clicked.connect(self.delete_department)
        d_layout.addWidget(btn_add_dept); d_layout.addWidget(btn_del_dept)
        
        # Staff Registration
        staff_tab = QWidget()
        staff_tab.setObjectName("LightPanel")
        staff_tab.setStyleSheet("padding: 25px;")
        s_container = QVBoxLayout(staff_tab)
        s_form_widget = QWidget(); s_layout = QFormLayout(s_form_widget)
        self.s_name = QLineEdit(); self.s_id = QLineEdit(); self.s_pass = QLineEdit()
        self.s_role = QComboBox(); self.s_role.addItems(["teacher", "hod"])
        self.s_dept = QComboBox()
        s_layout.addRow("Name:", self.s_name); s_layout.addRow("Teacher ID:", self.s_id); s_layout.addRow("Initial Password:", self.s_pass); s_layout.addRow("Role:", self.s_role); s_layout.addRow("Department:", self.s_dept)
        s_container.addWidget(s_form_widget)
        self.staff_table = QTableWidget(0, 3); self.staff_table.setHorizontalHeaderLabels(["ID", "Name", "Role"])
        registry_label = QLabel("Current Staff Registry:")
        registry_label.setStyleSheet("color: black; font-weight: bold; margin-top: 15px;")
        s_container.addWidget(registry_label)
        s_container.addWidget(self.staff_table)
        
        btn_manage_staff = QPushButton("Manage Selected Staff"); btn_manage_staff.setObjectName("PrimaryBtn")
        btn_manage_staff.clicked.connect(self.manage_staff_dialog)
        s_container.addWidget(btn_manage_staff)
        
        btn_reg_staff = QPushButton("REGISTER NEW STAFF MEMBER")
        btn_reg_staff.setMinimumHeight(50)
        btn_reg_staff.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: #000000;
                border-radius: 12px;
                padding: 12px;
                font-weight: 800;
                font-size: 14px;
                border: none;
            }
            QPushButton:hover { background-color: #34d399; }
            QPushButton:pressed { background-color: #059669; color: #ffffff; }
        """)
        btn_reg_staff.clicked.connect(self.register_staff)
        s_container.addWidget(btn_reg_staff)
        
        tabs.addTab(wrap_scroll(dept_tab), "Departments")
        tabs.addTab(wrap_scroll(staff_tab), "Staff Registration")
        tabs.addTab(self.create_reports_tab(), "Attendance Analytics")
        tabs.addTab(self.create_cloud_sync_tab(), "Cloud Sync Settings")
        tabs.addTab(self.create_camera_control_tab(), "Camera Control")
        layout.addWidget(tabs)
        self.stack.addWidget(self.admin_panel)
        self.refresh_admin_data()

    def toggle_camera(self):
        if self.thread.isRunning():
            self.thread.stop()
            if hasattr(self, 'cam_toggle'): self.cam_toggle.setText("TURN CAMERA ON")
            if hasattr(self, 'kiosk_cam_toggle'): self.kiosk_cam_toggle.setText("TURN CAMERA ON")
        else:
            self.thread = VideoThread(self.engine, self.cam_index)
            self.thread.change_pixmap_signal.connect(self.update_image)
            self.thread.face_detected_signal.connect(self.update_face_status)
            self.thread.start()
            if hasattr(self, 'cam_toggle'): self.cam_toggle.setText("TURN CAMERA OFF")
            if hasattr(self, 'kiosk_cam_toggle'): self.kiosk_cam_toggle.setText("TURN CAMERA OFF")

    def change_camera_index(self, index):
        self.cam_index = index
        if self.thread.isRunning():
            self.thread.stop()
            self.thread = VideoThread(self.engine, self.cam_index)
            self.thread.change_pixmap_signal.connect(self.update_image)
            self.thread.face_detected_signal.connect(self.update_face_status)
            self.thread.start()

    # --- HOD Panel ---
    def setup_hod_panel(self):
        self.hod_panel = QWidget()
        layout = QVBoxLayout(self.hod_panel)
        tabs = QTabWidget()
        
        # Student Registration (Moved to Kiosk Panel entirely)

        # Routine
        routine_tab = QWidget(); r_layout = QVBoxLayout(routine_tab)
        self.routine_table = QTableWidget(0, 7); 
        self.routine_table.setHorizontalHeaderLabels(["Day", "Time", "Paper Name", "Paper Code", "Sem", "Teacher", "Action"])
        r_layout.addWidget(self.routine_table)
        btn_add_routine = QPushButton("Add Routine Entry"); btn_add_routine.setObjectName("PrimaryBtn"); btn_add_routine.clicked.connect(self.add_routine_dialog)
        r_layout.addWidget(btn_add_routine)
        
        # Student Update Tab
        update_tab = QWidget()
        update_tab.setObjectName("LightPanel")
        update_tab.setStyleSheet("padding: 20px;")
        u_layout = QVBoxLayout(update_tab)
        self.stu_search = QLineEdit(); self.stu_search.setPlaceholderText("Enter Enrollment ID to Update")
        btn_fetch = QPushButton("Fetch Student Data"); btn_fetch.setObjectName("PrimaryBtn"); btn_fetch.clicked.connect(self.fetch_student_for_update)
        u_layout.addWidget(self.stu_search); u_layout.addWidget(btn_fetch)
        self.update_form = QFrame()
        self.update_form.setObjectName("LightPanel")
        self.update_form.setStyleSheet("padding: 10px;")
        self.u_form_layout = QFormLayout(self.update_form)
        self.u_name = QLineEdit(); self.u_sem = QLineEdit(); self.u_course = QLineEdit()
        self.u_form_layout.addRow("Name:", self.u_name); self.u_form_layout.addRow(self.STR_SEM, self.u_sem); self.u_form_layout.addRow("Course:", self.u_course)
        btn_save_u = QPushButton("Save Changes")
        btn_save_u.setObjectName("PrimaryBtn")
        btn_save_u.clicked.connect(self.save_student_update)
        
        btn_delete_u = QPushButton("Delete Student Permanently")
        btn_delete_u.setObjectName("DangerBtn")
        btn_delete_u.clicked.connect(self.delete_student)
        
        self.u_form_layout.addRow(btn_save_u)
        self.u_form_layout.addRow(btn_delete_u)
        u_layout.addWidget(self.update_form); self.update_form.hide()
        
        # Helper to wrap in scroll area
        def wrap_scroll(w):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(w)
            return scroll

        tabs.addTab(wrap_scroll(routine_tab), "Routine")
        tabs.addTab(wrap_scroll(routine_tab), "Routine")
        tabs.addTab(wrap_scroll(update_tab), "Update Students")
        tabs.addTab(self.create_student_directory_tab(), "Student Directory")
        tabs.addTab(self.create_promotion_tab(), "Student Promotion")
        tabs.addTab(self.create_reports_tab(), "Attendance Analytics")
        tabs.addTab(self.create_camera_control_tab(), "Camera Control")
        layout.addWidget(tabs)
        self.stack.addWidget(self.hod_panel)
        self.refresh_routine_data()

    # ── Student Directory Tab ─────────────────────────────────────────────────
    def create_student_directory_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header = QFrame()
        header.setObjectName("MainCard")
        header.setStyleSheet("padding: 16px;")
        h_layout = QHBoxLayout(header)

        title = QLabel("🎓  Student Directory")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #38bdf8;")
        h_layout.addWidget(title)
        h_layout.addStretch()

        # Semester filter
        sem_label = QLabel("Filter by Semester:")
        sem_label.setStyleSheet("color: #94a3b8; font-size: 13px;")
        h_layout.addWidget(sem_label)

        self.dir_sem_filter = QComboBox()
        self.dir_sem_filter.addItem("All Semesters")
        for s in range(1, 9):
            self.dir_sem_filter.addItem(f"Semester {s}", s)
        self.dir_sem_filter.setMinimumWidth(160)
        self.dir_sem_filter.setStyleSheet("""
            QComboBox {
                background-color: #1e293b; color: #f1f5f9;
                border: 1px solid #334155; border-radius: 8px;
                padding: 6px 12px; font-size: 13px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView { background-color: #1e293b; color: #f1f5f9; }
        """)
        self.dir_sem_filter.currentIndexChanged.connect(self.refresh_hod_student_dir)
        h_layout.addWidget(self.dir_sem_filter)

        # Search bar
        self.dir_search = QLineEdit()
        self.dir_search.setPlaceholderText("🔍  Search by name or enrollment...")
        self.dir_search.setMinimumWidth(220)
        self.dir_search.setStyleSheet("""
            QLineEdit {
                background-color: #1e293b; color: #f1f5f9;
                border: 1px solid #334155; border-radius: 8px;
                padding: 6px 12px; font-size: 13px;
            }
        """)
        self.dir_search.textChanged.connect(self.refresh_hod_student_dir)
        h_layout.addWidget(self.dir_search)

        # Refresh button
        btn_refresh = QPushButton("↻  Refresh")
        btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #0ea5e9; color: #ffffff;
                border-radius: 8px; padding: 7px 16px;
                font-weight: 700; border: none; font-size: 13px;
            }
            QPushButton:hover { background-color: #38bdf8; }
        """)
        btn_refresh.clicked.connect(self.refresh_hod_student_dir)
        h_layout.addWidget(btn_refresh)

        layout.addWidget(header)

        # Table
        self.student_dir_table = QTableWidget(0, 5)
        self.student_dir_table.setHorizontalHeaderLabels(
            ["#", "Name", "Enrollment No.", "Semester", "Major / Minor"]
        )
        self.student_dir_table.horizontalHeader().setStretchLastSection(True)
        self.student_dir_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.student_dir_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.student_dir_table.setAlternatingRowColors(True)
        self.student_dir_table.setStyleSheet("""
            QTableWidget {
                background-color: #0f172a;
                color: #f1f5f9;
                gridline-color: #1e293b;
                border: 1px solid #1e293b;
                border-radius: 10px;
                font-size: 13px;
            }
            QTableWidget::item:selected {
                background-color: #0ea5e9;
                color: #000000;
            }
            QTableWidget::item:alternate {
                background-color: #0c1527;
            }
            QHeaderView::section {
                background-color: #1e293b;
                color: #94a3b8;
                font-weight: 700;
                font-size: 12px;
                padding: 8px;
                border: none;
                border-bottom: 1px solid #334155;
            }
        """)
        # Column widths
        self.student_dir_table.setColumnWidth(0, 45)
        self.student_dir_table.setColumnWidth(1, 200)
        self.student_dir_table.setColumnWidth(2, 160)
        self.student_dir_table.setColumnWidth(3, 100)

        layout.addWidget(self.student_dir_table)

        # Status bar
        self.dir_status = QLabel("")
        self.dir_status.setStyleSheet("color: #64748b; font-size: 12px; padding: 4px;")
        layout.addWidget(self.dir_status)

        # Initial load
        self.refresh_hod_student_dir()
        return tab

    def refresh_hod_student_dir(self):
        """Reload the student directory table based on active semester filter and search."""
        from database.session import SessionLocal
        db = SessionLocal()
        try:
            sem_data = self.dir_sem_filter.currentData()  # None = All Semesters
            search = self.dir_search.text().strip().lower()

            # Fetch all students in HOD's department
            query = db.query(__import__('database.models', fromlist=['User']).User)
            query = query.filter_by(role='student')
            if hasattr(self, 'current_user') and self.current_user and self.current_user.department_id:
                query = query.filter_by(department_id=self.current_user.department_id)
            if sem_data is not None:
                query = query.filter_by(semester=sem_data)

            students = query.order_by(
                __import__('database.models', fromlist=['User']).User.semester,
                __import__('database.models', fromlist=['User']).User.name
            ).all()

            # Apply search filter client-side
            if search:
                students = [
                    s for s in students
                    if search in (s.name or "").lower() or search in (s.enrollment or "").lower()
                ]

            self.student_dir_table.setRowCount(0)
            for idx, s in enumerate(students, start=1):
                row = self.student_dir_table.rowCount()
                self.student_dir_table.insertRow(row)
                self.student_dir_table.setItem(row, 0, QTableWidgetItem(str(idx)))
                self.student_dir_table.setItem(row, 1, QTableWidgetItem(s.name or ""))
                self.student_dir_table.setItem(row, 2, QTableWidgetItem(s.enrollment or ""))
                sem_item = QTableWidgetItem(f"Sem {s.semester}" if s.semester else "—")
                sem_item.setTextAlignment(0x84)  # AlignCenter
                self.student_dir_table.setItem(row, 3, sem_item)
                self.student_dir_table.setItem(row, 4, QTableWidgetItem(s.major_minor or "—"))

            sem_label = self.dir_sem_filter.currentText()
            self.dir_status.setText(
                f"Showing {len(students)} student(s)  |  Filter: {sem_label}"
                + (f"  |  Search: '{search}'" if search else "")
            )
        except Exception as e:
            self.dir_status.setText(f"Error loading students: {e}")
        finally:
            db.close()

    def create_promotion_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        info_card = QFrame()
        info_card.setObjectName("MainCard")
        info_card.setStyleSheet("padding: 30px;")
        info_layout = QVBoxLayout(info_card)
        
        title = QLabel("Student Semester Promotion")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #38bdf8;")
        info_layout.addWidget(title)
        
        desc = QLabel("This action will:\n\n"
                     "1. Archive all current attendance records for selected students to the History database.\n"
                     "2. Reset the current attendance tables for the new semester.\n"
                     "3. Increment the semester field for all students in the selected department.\n\n"
                     "Note: Students will need to be re-verified in their new classes.")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #94a3b8; font-size: 14px; margin-top: 15px; margin-bottom: 20px;")
        info_layout.addWidget(desc)
        
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        
        self.promo_sem = QComboBox()
        self.promo_sem.addItems(["1", "2", "3", "4", "5", "6", "7", "8"])
        
        self.promo_dept = QComboBox()
        # Fetch current user's department for HOD
        if self.current_user.department:
            self.promo_dept.addItem(self.current_user.department.name, self.current_user.department_id)
            self.promo_dept.setEnabled(False) # HOD can only promote their own dept
        else:
            # Fallback for admin if they use this
            depts = crud.get_all_departments(self.db)
            for d in depts:
                self.promo_dept.addItem(d.name, d.id)
            
        form.addRow(QLabel("Current Semester:"), self.promo_sem)
        form.addRow(QLabel("Department:"), self.promo_dept)
        info_layout.addWidget(form_widget)
        
        btn_promote = QPushButton("EXECUTE SEMESTER PROMOTION")
        btn_promote.setObjectName("PrimaryBtn")
        btn_promote.setObjectName("DangerBtn")
        btn_promote.setMinimumHeight(55)
        btn_promote.clicked.connect(self.execute_promotion)
        info_layout.addWidget(btn_promote)
        
        layout.addWidget(info_card)
        layout.addStretch()
        return tab

    def execute_promotion(self):
        dept_id = self.promo_dept.currentData()
        current_sem = int(self.promo_sem.currentText())
        dept_name = self.promo_dept.currentText()
        
        reply = QMessageBox.question(
            self, 'Confirm Promotion', 
            f"Are you sure you want to promote students of Sem {current_sem} in {dept_name}?\n\n"
            "This will ARCHIVE all their current attendance records and increment their semester.\n\n"
            "THIS ACTION CANNOT BE UNDONE.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.statusBar().showMessage("Processing Promotion...")
                count = crud.promote_students(self.db, dept_id, current_sem)
                if count > 0:
                    QMessageBox.information(self, "Promotion Successful", 
                                          f"Successfully promoted {count} students in {dept_name}.\n"
                                          "Attendance records have been moved to History.")
                    self.show_notification(f"Promoted {count} students to Semester {current_sem + 1}")
                else:
                    QMessageBox.warning(self, "No Students Found", 
                                      f"No students found in Semester {current_sem} for {dept_name}.")
            except Exception as e:
                QMessageBox.critical(self, "System Error", f"Promotion failed: {str(e)}")
                self.db.rollback()
            finally:
                self.statusBar().showMessage("Ready")

    # --- Teacher Panel ---
    def setup_teacher_panel(self):
        self.teacher_panel = QWidget()
        layout = QVBoxLayout(self.teacher_panel)
        
        # --- Teacher Panel Tabs ---
        tabs = QTabWidget()
        
        # 1. Session Tab
        session_tab = QWidget(); s_layout = QVBoxLayout(session_tab)
        
        # Session Controls
        top_frame = QFrame()
        top_frame.setObjectName("LightPanel")
        top_frame.setStyleSheet("padding: 15px;")
        top_layout = QHBoxLayout(top_frame)
        self.t_paper = QLineEdit(); self.t_paper.setPlaceholderText("Paper Name")
        self.t_code = QLineEdit(); self.t_code.setPlaceholderText("Paper Code")
        self.t_sem = QLineEdit(); self.t_sem.setPlaceholderText("Sem")
        self.btn_session_control = QPushButton("Start Class Session")
        self.btn_session_control.setObjectName("PrimaryBtn")
        self.btn_session_control.clicked.connect(self.toggle_class_session)
        top_layout.addWidget(self.t_paper); top_layout.addWidget(self.t_code); top_layout.addWidget(self.t_sem); top_layout.addWidget(self.btn_session_control)
        s_layout.addWidget(top_frame)

        # Live Monitor
        self.monitor_frame = QFrame()
        self.monitor_frame.setObjectName("MainCard")
        self.monitor_frame.setStyleSheet("padding: 15px;")
        m_layout = QVBoxLayout(self.monitor_frame)

        # Session header row: title + elapsed timer
        m_header_layout = QHBoxLayout()
        mon_title = QLabel("🟢  Live Attendance Monitor")
        mon_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #38bdf8;")
        m_header_layout.addWidget(mon_title)
        m_header_layout.addStretch()
        self.session_clock_label = QLabel("Session: 00:00:00")
        self.session_clock_label.setStyleSheet("color: #94a3b8; font-size: 13px; font-weight: 600;")
        m_header_layout.addWidget(self.session_clock_label)
        m_layout.addLayout(m_header_layout)

        # Session elapsed timer
        self._session_start_time = None
        self.session_elapsed_timer = QTimer(self)
        self.session_elapsed_timer.setInterval(1000)
        self.session_elapsed_timer.timeout.connect(self._update_session_clock)

        tables_layout = QHBoxLayout()

        # Present Section
        p_vbox = QVBoxLayout()
        lbl_present = QLabel("✅  Present Students")
        lbl_present.setStyleSheet("color: #10b981; font-weight: bold; font-size: 13px; padding-bottom: 4px;")
        p_vbox.addWidget(lbl_present)
        self.monitor_table = QTableWidget(0, 5)
        self.monitor_table.setHorizontalHeaderLabels(["Image", "Enrollment", "Name", "Time", "Status"])
        self.monitor_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.monitor_table.setStyleSheet("""
            QTableWidget { background-color: #0f172a; color: #f1f5f9; gridline-color: #1e293b; }
            QHeaderView::section { background-color: #1e293b; color: #94a3b8; font-weight: 700; padding: 6px; border: none; }
        """)
        p_vbox.addWidget(self.monitor_table)

        # Absent Section
        a_vbox = QVBoxLayout()
        lbl_absent = QLabel("❌  Absent Students")
        lbl_absent.setStyleSheet("color: #ef4444; font-weight: bold; font-size: 13px; padding-bottom: 4px;")
        a_vbox.addWidget(lbl_absent)
        self.absent_table = QTableWidget(0, 2)
        self.absent_table.setHorizontalHeaderLabels(["Enrollment", "Name"])
        self.absent_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.absent_table.setStyleSheet("""
            QTableWidget { background-color: #0f172a; color: #f1f5f9; gridline-color: #1e293b; }
            QHeaderView::section { background-color: #1e293b; color: #94a3b8; font-weight: 700; padding: 6px; border: none; }
        """)
        a_vbox.addWidget(self.absent_table)

        tables_layout.addLayout(p_vbox, 3)
        tables_layout.addLayout(a_vbox, 1)
        m_layout.addLayout(tables_layout)
        s_layout.addWidget(self.monitor_frame)
        self.monitor_frame.hide()

        # Export button — hidden until a session starts/ends
        self.btn_report = QPushButton("📄  Export Daily PDF Report")
        self.btn_report.setStyleSheet("""
            QPushButton {
                background-color: #10b981; color: #000000;
                border-radius: 10px; padding: 10px; font-weight: 800;
                font-size: 13px; border: none;
            }
            QPushButton:hover { background-color: #34d399; }
            QPushButton:pressed { background-color: #059669; color: #ffffff; }
        """)
        self.btn_report.clicked.connect(self.export_teacher_report)
        self.btn_report.hide()   # Hidden until session is started
        s_layout.addWidget(self.btn_report)
        
        tabs.addTab(session_tab, "Class Session")
        tabs.addTab(self.create_reports_tab(), "Attendance Reports")
        tabs.addTab(self.create_camera_control_tab(), "Camera Settings")
        
        layout.addWidget(tabs)
        self.stack.addWidget(self.teacher_panel)
        
        # Initial Refresh (Sequenced and Safe)
        QTimer.singleShot(1000, self.refresh_routine_data)
        QTimer.singleShot(2000, self.refresh_reports)

    # --- Logic ---
    def refresh_admin_data(self):
        # Refresh Dept Table
        depts = crud.get_all_departments(self.db)
        if hasattr(self, 'dept_table'):
            self.dept_table.setRowCount(0)
            self.s_dept.clear()
            for d in depts:
                row = self.dept_table.rowCount()
                self.dept_table.insertRow(row)
                self.dept_table.setItem(row, 0, QTableWidgetItem(str(d.id)))
                self.dept_table.setItem(row, 1, QTableWidgetItem(d.name))
                self.s_dept.addItem(d.name, d.id)

        # Refresh Staff Table (single pass — duplicate removed)
        if hasattr(self, 'staff_table'):
            staff = crud.get_all_users(self.db)
            self.staff_table.setRowCount(0)
            for s in staff:
                if s.role in ['teacher', 'hod']:
                    row = self.staff_table.rowCount()
                    self.staff_table.insertRow(row)
                    self.staff_table.setItem(row, 0, QTableWidgetItem(s.enrollment))
                    self.staff_table.setItem(row, 1, QTableWidgetItem(s.name))
                    self.staff_table.setItem(row, 2, QTableWidgetItem(s.role.upper()))

    def add_department_dialog(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Department", "Enter Department Name:")
        if ok and name:
            crud.create_department(self.db, name)
            self.refresh_admin_data()

    def delete_department(self):
        row = self.dept_table.currentRow()
        if row >= 0:
            dept_id = int(self.dept_table.item(row, 0).text())
            crud.delete_department(self.db, dept_id)
            self.refresh_admin_data()
            QMessageBox.information(self, "Success", "Department deleted.")

    def register_staff(self):
        name = self.s_name.text().strip()
        eid = self.s_id.text().strip()
        pw = self.s_pass.text().strip()
        role = self.s_role.currentText()
        dept_id = self.s_dept.currentData()
        
        if not name or not eid or not pw:
            QMessageBox.warning(self, "Validation Error", "All fields (Name, ID, Password) are required.")
            return

        try:
            # Check if ID already exists
            existing = crud.get_user_by_enrollment(self.db, eid)
            if existing:
                QMessageBox.warning(self, "Error", f"A user with ID '{eid}' already exists.")
                return

            crud.create_user(self.db, str(uuid.uuid4()), name, eid, role=role, department_id=dept_id, password=pw)
            
            # 2. Sync to Cloud
            
            if self.session_cloud_pw:
                full_user = crud.get_user_by_enrollment(self.db, eid)
                user_data = {c.name: getattr(full_user, c.name) for c in full_user.__table__.columns}
                if 'embedding' in user_data and user_data['embedding']: user_data['embedding'] = user_data['embedding'].hex()
                threading.Thread(target=sync_client.upsert_user_cloud, 
                                args=(self.session_cloud_enrollment, self.session_cloud_pw, user_data), 
                                daemon=True).start()

            self.refresh_admin_data() # Update the table
            QMessageBox.information(self, "Success", f"{role.upper()} registered successfully and sync started.")
            self.s_name.clear(); self.s_id.clear(); self.s_pass.clear()
        except Exception as e:
            QMessageBox.critical(self, "Database Error", f"Could not register staff: {str(e)}")

    def manage_staff_dialog(self):
        row = self.staff_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Selection Error", "Please select a staff member from the table first.")
            return

        eid = self.staff_table.item(row, 0).text()
        user = crud.get_user_by_enrollment(self.db, eid)
        if not user: return

        from PyQt6.QtWidgets import QDialog, QLineEdit, QFormLayout, QComboBox
        dialog = QDialog(self); dialog.setWindowTitle(f"Manage Staff: {user.name}")
        dialog.setMinimumWidth(420)
        dialog.setStyleSheet(self.STR_DIALOG_STYLE)
        
        d_layout = QVBoxLayout(dialog)
        form_widget = QWidget(); f_layout = QFormLayout(form_widget)
        
        name_input = QLineEdit(user.name)
        pass_input = QLineEdit()
        pass_input.setPlaceholderText("Leave blank to keep current")
        
        role_input = QComboBox()
        role_input.addItems(["teacher", "hod"])
        role_input.setCurrentText(user.role)
        
        dept_input = QComboBox()
        depts = crud.get_all_departments(self.db)
        for d in depts:
            dept_input.addItem(d.name, d.id)
            if d.id == user.department_id:
                dept_input.setCurrentIndex(dept_input.count() - 1)
        
        f_layout.addRow("Full Name:", name_input)
        f_layout.addRow("New Password:", pass_input)
        f_layout.addRow("Role:", role_input)
        f_layout.addRow("Department:", dept_input)
        d_layout.addWidget(form_widget)
        
        btn_save = QPushButton("Save Changes"); btn_save.setObjectName("PrimaryBtn")
        btn_del = QPushButton("Delete Staff Member"); btn_del.setObjectName("DangerBtn")
        
        d_layout.addWidget(btn_save); d_layout.addWidget(btn_del)
        
        def save_changes():
            updates = {
                "name": name_input.text().strip(),
                "role": role_input.currentText(),
                "department_id": dept_input.currentData()
            }
            if pass_input.text().strip():
                from database.crud import get_password_hash
                updates["password_hash"] = get_password_hash(pass_input.text().strip())
            
            # 1. Update Locally
            crud.update_student(self.db, eid, **updates)
            
            # 2. Sync to Cloud
            
            if self.session_cloud_pw:
                full_user = crud.get_user_by_enrollment(self.db, eid)
                if full_user:
                    user_data = {c.name: getattr(full_user, c.name) for c in full_user.__table__.columns}
                    if 'embedding' in user_data and user_data['embedding']: user_data['embedding'] = user_data['embedding'].hex()
                    threading.Thread(target=sync_client.upsert_user_cloud, 
                                    args=(self.session_cloud_enrollment, self.session_cloud_pw, user_data), 
                                    daemon=True).start()
                
            QMessageBox.information(dialog, "Success", "Staff updated and sync started.")
            self.refresh_admin_data()
            dialog.accept()
            
        def delete_staff():
            reply = QMessageBox.question(dialog, "Confirm Delete", 
                                       f"Permanently delete {user.role.upper()} {user.name}?\nThis cannot be undone.",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                crud.delete_user(self.db, eid)
                
                # Cloud Sync — prompt for password if not cached
            
                if self.session_cloud_pw:
                    threading.Thread(target=sync_client.delete_user_cloud, 
                                    args=(self.session_cloud_enrollment, self.session_cloud_pw, eid), 
                                    daemon=True).start()
                
                QMessageBox.information(dialog, "Deleted", "Staff member removed and cloud sync started.")
                self.refresh_admin_data()
                dialog.accept()

        btn_save.clicked.connect(save_changes)
        btn_del.clicked.connect(delete_staff)
        dialog.exec()

    def add_routine_dialog(self):
        from PyQt6.QtWidgets import QDialog, QTimeEdit, QComboBox
        dialog = QDialog(self); dialog.setWindowTitle("Add Routine")
        dialog.setStyleSheet(self.STR_DIALOG_STYLE)
        d_layout = QFormLayout(dialog)
        day = QComboBox(); day.addItems(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
        start = QTimeEdit(); start.setDisplayFormat("h:mm AP")
        end = QTimeEdit(); end.setDisplayFormat("h:mm AP")
        paper = QLineEdit(); code = QLineEdit(); sem = QLineEdit()
        
        # Teacher selection
        teachers = crud.get_all_users(self.db, role='teacher')
        t_combo = QComboBox()
        for t in teachers: t_combo.addItem(t.name, t.id)
        
        d_layout.addRow("Day:", day); d_layout.addRow("Start Time:", start); d_layout.addRow("End Time:", end)
        d_layout.addRow("Paper Name:", paper); d_layout.addRow("Paper Code:", code); d_layout.addRow(self.STR_SEM, sem)
        d_layout.addRow("Teacher:", t_combo)
        
        btn = QPushButton("Save")
        btn.clicked.connect(dialog.accept)
        d_layout.addRow(btn)
        
        if dialog.exec():
            # Get or create subject first
            subj = crud.get_or_create_subject(self.db, code.text().strip(), paper.text().strip())
            
            # 1. Create Locally
            new_r = crud.create_routine(self.db, day.currentText(), start.text(), end.text(), 
                                       subj.id, int(sem.text() or 0), 
                                       t_combo.currentData(), self.current_user.department_id)
            
            # 2. Sync Routine
            
            if self.session_cloud_pw:
                routine_data = {c.name: getattr(new_r, c.name) for c in new_r.__table__.columns}
                threading.Thread(target=sync_client.upsert_routine_cloud, 
                                args=(self.session_cloud_enrollment, self.session_cloud_pw, routine_data), 
                                daemon=True).start()

            self.refresh_routine_data()
            QMessageBox.information(self, "Success", "Routine entry added and sync started.")

    def fetch_student_for_update(self):
        enroll = self.stu_search.text().strip()
        student = crud.get_user_by_enrollment(self.db, enroll)
        if student:
            self.u_name.setText(student.name); self.u_sem.setText(str(student.semester or 0))
            self.u_course.setText(student.course_name or "")
            self.update_form.show()
        else:
            QMessageBox.warning(self, "Not Found", "Student not found.")

    def save_student_update(self):
        enroll = self.stu_search.text().strip()
        crud.update_student(self.db, enroll, name=self.u_name.text(), 
                           semester=int(self.u_sem.text() or 0), 
                           course_name=self.u_course.text())
        
        # Cloud Sync
            
        if self.session_cloud_pw:
            user = crud.get_user_by_enrollment(self.db, enroll)
            if user:
                data = {c.name: getattr(user, c.name) for c in user.__table__.columns}
                if 'embedding' in data and data['embedding']: data['embedding'] = data['embedding'].hex()
                threading.Thread(target=sync_client.upsert_user_cloud, 
                                args=(self.session_cloud_enrollment, self.session_cloud_pw, data), 
                                daemon=True).start()

        QMessageBox.information(self, "Success", "Student updated and sync started.")
        self.update_form.hide()

    def delete_student(self):
        enroll = self.stu_search.text().strip()
        if not enroll: return
        
        reply = QMessageBox.question(self, "Confirm Delete", 
                                   f"Are you sure you want to permanently delete student with Enrollment ID '{enroll}'?\nThis will also remove all their attendance records.",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            if crud.delete_user(self.db, enroll):
                # Cloud Sync — use pre-loaded admin credentials from .env
                if self.session_cloud_pw:
                    threading.Thread(target=sync_client.delete_user_cloud, 
                                    args=(self.session_cloud_enrollment, self.session_cloud_pw, enroll), 
                                    daemon=True).start()

                QMessageBox.information(self, "Deleted", "Student and all associated records have been removed. Cloud sync started.")
                self.update_form.hide()
                self.stu_search.clear()
            else:
                QMessageBox.warning(self, "Error", "Could not find student to delete.")

    def enroll_student(self):
        if self.current_embedding is None or not self.is_live:
            QMessageBox.warning(self, "Error", "Face and Liveness required for student enrollment.")
            return
        
        name = self.stu_name.text(); enroll = self.stu_enroll.text()
        sem = int(self.stu_sem.text() or 0); course = self.stu_course.text()
        major = self.stu_major.text()
        
        if name and enroll:
            try:
                crud.create_user(self.db, str(uuid.uuid4()), name, enroll, role='student', 
                                 department_id=self.current_user.department_id,
                                 semester=sem, course_name=course, major_minor=major,
                                 embedding=self.current_embedding)
                
                # 2. Sync to Cloud
            
                if self.session_cloud_pw:
                    full_user = crud.get_user_by_enrollment(self.db, enroll)
                    if full_user:
                        user_data = {c.name: getattr(full_user, c.name) for c in full_user.__table__.columns}
                        if 'embedding' in user_data and user_data['embedding']: user_data['embedding'] = user_data['embedding'].hex()
                        threading.Thread(target=sync_client.upsert_user_cloud, 
                                        args=(self.session_cloud_enrollment, self.session_cloud_pw, user_data), 
                                        daemon=True).start()

                self.show_timed_msg("Success", f"Student {name} enrolled!", 1000)
                self.stu_name.clear(); self.stu_enroll.clear()
            except Exception as e:
                self.db.rollback()
                if "UniqueViolation" in str(e) or "already exists" in str(e).lower():
                    QMessageBox.warning(self, "Duplicate Error", f"Enrollment ID '{enroll}' is already registered to another student.")
                else:
                    QMessageBox.critical(self, "Enrollment Error", f"Failed to register student: {e}")

    def toggle_class_session(self):
        if not hasattr(self, 'active_session') or self.active_session is None:
            # Start Session
            p_name = self.t_paper.text().strip() or "Ad-hoc Class"
            p_code = self.t_code.text().strip() or "ADHOC"
            sem_text = self.t_sem.text().strip()
            sem = int(sem_text) if sem_text.isdigit() else 0
            
            # Try to find a matching routine to get an ID for reporting
            db = SessionLocal()
            rid = None
            try:
                routine = db.query(models.Routine).join(models.Subject).filter(
                    models.Routine.department_id == self.current_user.department_id,
                    models.Routine.semester == sem
                ).filter(
                    (models.Subject.code == p_code) | (models.Subject.name.ilike(p_name))
                ).first()
                if routine: 
                    rid = routine.id
                else:
                    import datetime
                    subj = crud.get_or_create_subject(db, p_code, p_name)
                    now = datetime.datetime.now()
                    new_routine = models.Routine(
                        day_of_week=now.strftime("%A"),
                        start_time=(now - datetime.timedelta(minutes=5)).time(),
                        end_time=(now + datetime.timedelta(hours=2)).time(),
                        semester=sem,
                        subject_id=subj.id,
                        teacher_id=self.current_user.id,
                        department_id=self.current_user.department_id
                    )
                    db.add(new_routine)
                    db.commit()
                    db.refresh(new_routine)
                    rid = new_routine.id
            except Exception as e:
                print(f"Routine lookup error: {e}")
            finally:
                db.close()

            self.active_session = {
                "paper_name": p_name,
                "paper_code": p_code,
                "semester": sem,
                "routine_id": rid
            }
            self.monitor_table.setRowCount(0)
            self.absent_table.setRowCount(0)

            # Populate Absent Table
            # Fix #2: When sem=0 (ad-hoc), fetch all dept students regardless of semester
            db = SessionLocal()
            try:
                if sem and sem > 0:
                    students = crud.get_students_by_dept_sem(db, self.current_user.department_id, sem)
                else:
                    all_students = crud.get_all_users(db, role='student')
                    students = [s for s in all_students if s.department_id == self.current_user.department_id]
                for s in students:
                    row = self.absent_table.rowCount()
                    self.absent_table.insertRow(row)
                    self.absent_table.setItem(row, 0, QTableWidgetItem(s.enrollment))
                    self.absent_table.setItem(row, 1, QTableWidgetItem(s.name))
            except Exception as e:
                print(f"Error populating absent list: {e}")
            finally:
                db.close()

            # Start session clock
            import time as _time
            self._session_start_time = _time.time()
            self.session_elapsed_timer.start()

            self.monitor_frame.show()
            self.btn_report.show()   # Fix #3: show export button when session starts
            self.btn_session_control.setText("End Class Session")
            self.btn_session_control.setObjectName("DangerBtn")
            self.btn_session_control.style().unpolish(self.btn_session_control)
            self.btn_session_control.style().polish(self.btn_session_control)
            QMessageBox.information(self, "Session Started", f"Attendance is now active for {self.active_session['paper_name']}")
        else:
            # End Session
            self.last_session = self.active_session
            self.active_session = None
            self.session_elapsed_timer.stop()   # Fix #5: stop clock
            self.monitor_frame.hide()
            self.btn_session_control.setText("Start Class Session")
            self.btn_session_control.setObjectName("PrimaryBtn")
            self.btn_session_control.style().unpolish(self.btn_session_control)
            self.btn_session_control.style().polish(self.btn_session_control)
            QMessageBox.information(self, "Session Ended", "Class session has been closed. You can still export the PDF report.")

    def _update_session_clock(self):
        """Update the elapsed session timer label every second."""
        if self._session_start_time is None:
            return
        import time as _time
        elapsed = int(_time.time() - self._session_start_time)
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60
        self.session_clock_label.setText(f"Session: {h:02d}:{m:02d}:{s:02d}")

    def export_analytics_pdf(self):
        if self.report_table.rowCount() == 0:
            QMessageBox.warning(self, self.STR_EXP_ERR, "The table is empty. Please click 'Generate Report' to load data before exporting.")
            return
            
        from utils.reports import generate_pdf_report
        import datetime
        
        class MockRecord:
            def __init__(self, date, enrollment, name, paper):
                class MockUser:
                    def __init__(self, e, n): self.enrollment = e; self.name = n
                self.user = MockUser(enrollment, name)
                self.timestamp = datetime.datetime.strptime(date, "%Y-%m-%d")
                self.paper = paper

        records = []
        for i in range(self.report_table.rowCount()):
            d = self.report_table.item(i, 0).text()
            e = self.report_table.item(i, 1).text()
            n = self.report_table.item(i, 2).text()
            p = self.report_table.item(i, 3).text()
            records.append(MockRecord(d, e, n, p))

        paper_text = self.r_paper.currentText()
        paper_code = ""
        if " (" in paper_text:
            parts = paper_text.split(" (")
            paper_name = parts[0]
            paper_code = parts[1].replace(")", "")
        else:
            paper_name = paper_text

        title = f"Attendance Report: {paper_name} ({self.r_period.currentText()})"
        filename = f"Report_{paper_name.replace(' ', '_')}_{datetime.datetime.now().strftime('%Y%m%d')}.pdf"
        
        # Refresh user to ensure relationships are loaded
        self.db.add(self.current_user)
        self.db.refresh(self.current_user)

        metadata = {
            "dept": self.current_user.department.name if self.current_user.department else "N/A",
            "teacher": self.current_user.name,
            "paper": paper_name,
            "code": paper_code,
            "sem": self.r_sem.currentText()
        }
        
        try:
            path = generate_pdf_report(title, records, filename, metadata=metadata)
            QMessageBox.information(self, "Success", f"Analytics report exported to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, self.STR_EXP_ERR, f"Could not export PDF: {str(e)}")

    def export_teacher_report(self):
        session_to_export = getattr(self, 'active_session', None)
        if not session_to_export:
            session_to_export = getattr(self, 'last_session', None)

        if not session_to_export:
            QMessageBox.warning(self, "Error", "No active session to export.")
            return
        if self.monitor_table.rowCount() == 0 and self.absent_table.rowCount() == 0:
            QMessageBox.warning(self, self.STR_EXP_ERR, "No students found in the roster or marked present for this session.")
            return
            
        from utils.reports import generate_pdf_report
        import datetime
        
        # Mocking record objects for the utility
        class MockRecord:
            def __init__(self, enrollment, name, timestamp, paper, status="Present"):
                class MockUser:
                    def __init__(self, e, n): self.enrollment = e; self.name = n
                self.user = MockUser(enrollment, name)
                self.timestamp = timestamp
                self.paper = paper
                self.status = status

        records = []
        # 1. Add Present Students
        for i in range(self.monitor_table.rowCount()):
            e = self.monitor_table.item(i, 1).text()
            n = self.monitor_table.item(i, 2).text()
            t_str = self.monitor_table.item(i, 3).text()
            try:
                t = datetime.datetime.combine(datetime.date.today(), datetime.datetime.strptime(t_str, "%H:%M:%S").time())
            except:
                t = datetime.datetime.now()
            records.append(MockRecord(e, n, t, session_to_export['paper_name'], status="Present"))

        # 2. Add Absent Students
        for i in range(self.absent_table.rowCount()):
            e = self.absent_table.item(i, 0).text()
            n = self.absent_table.item(i, 1).text()
            records.append(MockRecord(e, n, datetime.datetime.now(), session_to_export['paper_name'], status="Absent"))
        title = f"Class Attendance: {session_to_export['paper_name']}"
        filename = f"Attendance_{session_to_export['paper_code']}_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        
        # Refresh user to ensure relationships are loaded
        self.db.add(self.current_user)
        self.db.refresh(self.current_user)

        metadata = {
            "dept": self.current_user.department.name if self.current_user.department else "N/A",
            "teacher": self.current_user.name,
            "paper": session_to_export['paper_name'],
            "code": session_to_export['paper_code'],
            "sem": session_to_export['semester']
        }
        
        try:
            path = generate_pdf_report(title, records, filename, metadata=metadata)
            QMessageBox.information(self, "Success", f"Report exported to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, self.STR_EXP_ERR, f"Could not export PDF: {str(e)}")

    # --- Core Handlers ---
    def update_image(self, cv_img):
        try:
            if sip.isdeleted(self) or not self.isVisible(): return
            if sip.isdeleted(self.image_label): return
            
            rgb_image = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            q_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            label_w = self.image_label.width() or 640
            label_h = self.image_label.height() or 480
            self.image_label.setPixmap(QPixmap.fromImage(q_img.scaled(label_w, label_h, Qt.AspectRatioMode.KeepAspectRatio)))
        except Exception: pass

    def update_face_status(self, embedding, box, is_live):
        try:
            if sip.isdeleted(self) or not self.isVisible(): return
            if sip.isdeleted(self.status_label): return

            self.current_embedding = embedding
            self.is_live = is_live
            if embedding is not None:
                if is_live:
                    if hasattr(self, 'active_session') and self.active_session is not None:
                        self.status_label.setText("Verifying Identity...")
                    else:
                        self.status_label.setText("Camera Active — Start a session to mark attendance")

                    # Fix #7: Only auto-mark when a session is actually active
                    if (hasattr(self, 'active_session') and self.active_session
                            and time.time() - self.last_mark_time > self.auto_mark_delay):
                        self.mark_attendance(box)
                else:
                    self.status_label.setText("Liveness Check Failed (Blink to Verify)")
            else:
                self.status_label.setText("Searching for Faces...")
        except Exception as e:
            print(f"Face status update failed: {e}")

    def closeEvent(self, event):
        if hasattr(self, 'thread'):
            try:
                self.thread.change_pixmap_signal.disconnect()
                self.thread.face_detected_signal.disconnect()
            except Exception: pass
            
            if self.thread.isRunning():
                self.thread.stop()
                self.thread.wait()
        event.accept()

    def identify_user(self):
        db = SessionLocal()
        try:
            # Fix #1: Scan only students in the teacher's own department
            # This prevents false matches against staff/admins and improves speed
            dept_id = getattr(self.current_user, 'department_id', None)
            all_users = crud.get_all_users(db, role='student')
            if dept_id:
                users = [u for u in all_users if u.department_id == dept_id]
            else:
                users = all_users

            best_match = None; min_dist = 0.8
            for user in users:
                if not user.embedding: continue
                db_emb = np.frombuffer(user.embedding, dtype=np.float32)

                # Normalize for consistent cosine comparison
                db_emb = db_emb / np.linalg.norm(db_emb)

                match, dist = self.engine.compare_embeddings(self.current_embedding, db_emb, threshold=1.0)
                if match and dist < min_dist:
                    min_dist = dist
                    best_match = {
                        "id": user.id,
                        "user_id": user.user_id,
                        "name": user.name,
                        "enrollment": user.enrollment
                    }
        except Exception as e:
            print(f"Identification Error: {e}")
        finally:
            db.close()
            
        if not best_match:
            print(f"Face detected but no match found (min_dist observed: {min_dist})")
            
        return best_match, min_dist

    def add_to_live_monitor(self, user_data, box):
        if not (self.current_user.role == 'teacher' and hasattr(self, 'monitor_table')):
            return

        # 1. Remove from Absent Table if present
        if hasattr(self, 'absent_table'):
            for i in range(self.absent_table.rowCount()):
                item = self.absent_table.item(i, 0)
                if item and item.text() == user_data['enrollment']:
                    self.absent_table.removeRow(i)
                    break

        # 2. Duplicate Check for Present Table
        for i in range(self.monitor_table.rowCount()):
            item = self.monitor_table.item(i, 1)
            if item and item.text() == user_data['enrollment']:
                return

        # Insert at the top for better visibility
        row = 0
        self.monitor_table.insertRow(row)
        
        # Face Crop Logic
        if hasattr(self.thread, 'current_cv_img') and self.thread.isRunning():
            try:
                face_img = self.thread.current_cv_img.copy()
                if box is not None:
                    x1, y1, x2, y2 = [int(b) for b in box]
                    h, w = face_img.shape[:2]
                    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
                    crop = face_img[y1:y2, x1:x2]
                    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                    q_img = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.shape[1]*3, QImage.Format.Format_RGB888)
                    self.monitor_table.setItem(row, 0, QTableWidgetItem(QIcon(QPixmap.fromImage(q_img)), ""))
            except Exception as e:
                print(f"Crop Error: {e}")

        import time
        self.monitor_table.setItem(row, 1, QTableWidgetItem(user_data['enrollment']))
        self.monitor_table.setItem(row, 2, QTableWidgetItem(user_data['name']))
        self.monitor_table.setItem(row, 3, QTableWidgetItem(time.strftime("%H:%M:%S")))
        self.monitor_table.setItem(row, 4, QTableWidgetItem("Present"))

    def mark_attendance(self, box=None):
        best_match, min_dist = self.identify_user()
        if not best_match: return

        db = SessionLocal()
        try:
            rid = self.active_session.get("routine_id") if hasattr(self, 'active_session') and self.active_session else None
            res = crud.mark_attendance(db, best_match["id"], "KIOSK_1", float(1.0 - min_dist), routine_id=rid)
            if res["status"] == "success":
                self.last_mark_time = time.time()
                self.show_notification(f"Attendance Marked for {best_match['name']}")
                self.show_timed_msg("Attendance Marked", f"Welcome, {best_match['name']}", 800)
                self.add_to_live_monitor(best_match, box)
            elif res["status"] == "duplicate":
                self.status_label.setText(f"{best_match['name']} already marked.")
                self.show_notification(f"{best_match['name']} already marked today", is_error=False)
                self.last_mark_time = time.time()
                self.add_to_live_monitor(best_match, box)
            else:
                self.status_label.setText(res.get("message", "Error marking attendance"))
                self.show_notification(res.get("message", "Error"), is_error=True)
                self.last_mark_time = time.time()
        except Exception as e:
            import traceback
            err = traceback.format_exc()
            self.status_label.setText(f"System Error: {str(e)}")
            try:
                with open("attendance_crash.log", "w", encoding="utf-8") as f:
                    f.write(err)
            except: pass
            print(f"Attendance Error: {err}")
        finally:
            db.close()

    def show_timed_msg(self, title, text, ms=800):
        msg = QMessageBox(self)
        msg.setWindowTitle(title); msg.setText(text)
        msg.setStandardButtons(QMessageBox.StandardButton.NoButton)
        QTimer.singleShot(ms, msg.accept); msg.exec()

    def run_sync(self):
        if not self.sync_thread.isRunning():
            self.show_notification("Syncing with server...", is_error=False)
            self.sync_thread.start()

    def handle_sync_result(self, message):
        is_error = "failed" in message.lower()
        self.show_notification(message, is_error=is_error)
        self.statusBar().showMessage(message, 10000 if is_error else 5000)
        
        if is_error:
            QMessageBox.critical(self, "Sync Status", message)
        else:
            QMessageBox.information(self, "Sync Status", message)

    def check_for_updates_manually(self):
        if not self.version_thread.isRunning():
            self.btn_check_updates.setEnabled(False)
            self.btn_check_updates.setText(" Checking...")
            self.version_thread.start()

    def handle_version_result(self, info):
        self.btn_check_updates.setEnabled(True)
        self.btn_check_updates.setText(" Check for Updates")
        
        if "error" in info:
            QMessageBox.warning(self, "Update Check Failed", info["error"])
        elif info:
            self.show_update_popup(info)
        else:
            QMessageBox.information(self, "Up to Date", "You are running the latest version of BNC Attendance.")

    def show_update_popup(self, info):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("Update Available")
        text = f"A new version ({info['version']}) is available!\n\n"
        text += f"{info.get('message', '')}\n\n"
        text += "Would you like to download it now?"
        msg.setText(text)
        
        btn_download = msg.addButton("Download Now", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        
        msg.exec()
        
        if msg.clickedButton() == btn_download:
            import webbrowser
            webbrowser.open(info.get('download_url', 'https://example.com'))

    def refresh_routine_data(self):
        db = SessionLocal()
        try:
            routines = crud.get_routines_by_dept(db, self.current_user.department_id)
            # Update HOD Routine Table
            if hasattr(self, 'routine_table'):
                self.routine_table.setRowCount(0)
                for r in routines:
                    row = self.routine_table.rowCount()
                    self.routine_table.insertRow(row)
                    self.routine_table.setItem(row, 0, QTableWidgetItem(r.day_of_week))
                    s_str = r.start_time.strftime("%I:%M %p") if r.start_time else "N/A"
                    e_str = r.end_time.strftime("%I:%M %p") if r.end_time else "N/A"
                    self.routine_table.setItem(row, 1, QTableWidgetItem(f"{s_str} - {e_str}"))
                    self.routine_table.setItem(row, 2, QTableWidgetItem(r.subject.name if r.subject else "N/A"))
                    self.routine_table.setItem(row, 3, QTableWidgetItem(r.subject.code if r.subject else "N/A"))
                    self.routine_table.setItem(row, 4, QTableWidgetItem(str(r.semester)))
                    self.routine_table.setItem(row, 5, QTableWidgetItem(r.teacher.name if r.teacher else "N/A"))
                    
                    # Delete Button
                    btn_del = QPushButton("Delete")
                    btn_del.setStyleSheet("background-color: #ef4444; color: white; border-radius: 4px; padding: 4px;")
                    btn_del.clicked.connect(lambda checked, rid=r.id: self.delete_routine_action(rid))
                    self.routine_table.setCellWidget(row, 6, btn_del)

            # Update Analytics Paper Filter
            if hasattr(self, 'r_paper'):
                current = self.r_paper.currentText()
                self.r_paper.clear()
                self.r_paper.addItem("All Papers")
                seen_papers = set()
                for r in routines:
                    if r.subject:
                        p_label = f"{r.subject.name} ({r.subject.code})" if r.subject.code else r.subject.name
                        if p_label not in seen_papers:
                            self.r_paper.addItem(p_label)
                            seen_papers.add(p_label)
                idx = self.r_paper.findText(current)
                if idx >= 0: self.r_paper.setCurrentIndex(idx)
        except Exception as e:
            print(f"Error refreshing routine: {e}")
        finally:
            db.close()

    def _get_attendance_records(self, db, period, sem):
        if period == "Daily":
            recs = crud.get_filtered_attendance(db, self.current_user.department_id, sem, days=1)
            
            # If teacher has an active session, filter only for that paper
            if hasattr(self, 'active_session') and self.active_session:
                p_code = self.active_session.get("paper_code")
                p_name = self.active_session.get("paper_name")
                if p_code:
                    return [r for r in recs if r.routine and r.routine.subject and r.routine.subject.code == p_code]
                else:
                    return [r for r in recs if r.routine and r.routine.subject and r.routine.subject.name == p_name]
            
            return recs
        
        days = 7 if period == "Weekly" else 30
        return crud.get_filtered_attendance(db, self.current_user.department_id, sem, days)

    def _apply_report_filters(self, records, paper_filter):
        seen, unique = set(), []
        paper_filter = paper_filter.strip().lower()
        
        for r in records:
            p_name = r.routine.subject.name if r.routine and r.routine.subject else "Uncategorized (Legacy)"
            p_code = r.routine.subject.code if r.routine and r.routine.subject else ""
            disp = (f"{p_name} ({p_code})" if p_code else p_name).strip().lower()
            
            # Allow "Uncategorized" records to show if "All Papers" is selected
            if paper_filter != "all papers" and paper_filter != disp:
                continue
                
            key = (r.timestamp.strftime("%Y-%m-%d"), r.user.enrollment, p_name)
            if key not in seen:
                seen.add(key); unique.append(r)
        return unique

    def refresh_reports(self):
        db = SessionLocal()
        try:
            period = self.r_period.currentText()
            paper_f = self.r_paper.currentText().strip().lower()
            sem_text = self.r_sem.currentText()
            sem = int(sem_text) if sem_text.isdigit() else None
            
            records = self._get_attendance_records(db, period, sem)
            unique_records = self._apply_report_filters(records, paper_f)

            self.report_table.setRowCount(0)
            self.r_status_label.setText(f"Results for: {self.r_paper.currentText()} ({period})")
            
            for r in unique_records:
                row = self.report_table.rowCount()
                self.report_table.insertRow(row)
                self.report_table.setItem(row, 0, QTableWidgetItem(r.timestamp.strftime("%Y-%m-%d")))
                self.report_table.setItem(row, 1, QTableWidgetItem(r.user.enrollment))
                self.report_table.setItem(row, 2, QTableWidgetItem(r.user.name))
                self.report_table.setItem(row, 3, QTableWidgetItem(r.routine.subject.name if r.routine and r.routine.subject else "Uncategorized (Legacy)"))
        except Exception as e:
            print(f"Error refreshing reports: {e}")
            self.r_status_label.setText("Error loading data. Retrying...")
        finally:
            db.close()

    def delete_routine_action(self, rid):
        reply = QMessageBox.question(self, "Confirm Delete", "Are you sure you want to delete this routine entry?", 
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            # 1. Local Delete
            crud.delete_routine(self.db, rid)
            
            # 2. Cloud Delete
            
            if self.session_cloud_pw:
                threading.Thread(target=sync_client.delete_routine_cloud, 
                                args=(self.session_cloud_enrollment, self.session_cloud_pw, rid), 
                                daemon=True).start()
            
            self.refresh_routine_data()
            QMessageBox.information(self, "Success", "Routine entry deleted and sync started.")


    def create_cloud_sync_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # ── Header ────────────────────────────────────────────────────────────
        header = QFrame()
        header.setObjectName("MainCard")
        header.setStyleSheet("padding: 20px;")
        h_layout = QVBoxLayout(header)

        title = QLabel("☁  Cloud Synchronization Management")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #38bdf8;")
        h_layout.addWidget(title)

        desc = QLabel("Synchronize your local database with the central cloud server.\n"
                      "Use Pull to download cloud data locally, or Full Sync to upload your local data to the cloud.")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #94a3b8; font-size: 13px; margin-top: 6px;")
        h_layout.addWidget(desc)
        layout.addWidget(header)

        # ── Pull Section ───────────────────────────────────────────────────────
        pull_group = QFrame()
        pull_group.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border-radius: 14px;
                border-left: 4px solid #38bdf8;
            }
        """)
        pg_layout = QVBoxLayout(pull_group)
        pg_layout.setContentsMargins(20, 18, 20, 18)
        pg_layout.setSpacing(8)

        pull_title = QLabel("⬇   Option A: Download Master Data  (Pull from Cloud)")
        pull_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #f1f5f9;")
        pg_layout.addWidget(pull_title)

        pull_desc = QLabel("Downloads all students, staff, routines, and departments from the cloud "
                           "and saves them to your local database. Use this on a fresh install or to "
                           "get updates from the central server.")
        pull_desc.setWordWrap(True)
        pull_desc.setStyleSheet("color: #94a3b8; font-size: 13px;")
        pg_layout.addWidget(pull_desc)

        btn_pull = QPushButton("⬇   Pull Master Data from Cloud")
        btn_pull.setObjectName("PrimaryBtn")
        btn_pull.setMinimumHeight(48)
        btn_pull.setStyleSheet("""
            QPushButton {
                background-color: #0ea5e9;
                color: #ffffff;
                border-radius: 10px;
                font-size: 14px;
                font-weight: 700;
                border: none;
                padding: 10px 20px;
            }
            QPushButton:hover { background-color: #38bdf8; }
            QPushButton:pressed { background-color: #0284c7; }
        """)
        btn_pull.clicked.connect(self.pull_master_data_dialog)
        pg_layout.addWidget(btn_pull)
        layout.addWidget(pull_group)

        # ── Push Section ───────────────────────────────────────────────────────
        push_group = QFrame()
        push_group.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border-radius: 14px;
                border-left: 4px solid #10b981;
            }
        """)
        ps_layout = QVBoxLayout(push_group)
        ps_layout.setContentsMargins(20, 18, 20, 18)
        ps_layout.setSpacing(8)

        push_title = QLabel("⬆   Option B: Upload Local Data  (Full Sync to Cloud)")
        push_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #f1f5f9;")
        ps_layout.addWidget(push_title)

        push_desc = QLabel("Pushes ALL your local students, staff, routines, and departments to the "
                           "cloud. Existing cloud records are updated. Use this to share your local "
                           "database with all other connected devices.")
        push_desc.setWordWrap(True)
        push_desc.setStyleSheet("color: #94a3b8; font-size: 13px;")
        ps_layout.addWidget(push_desc)

        btn_push = QPushButton("⬆   Full Sync: Push All Data to Cloud")
        btn_push.setMinimumHeight(48)
        btn_push.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: #000000;
                border-radius: 10px;
                font-size: 14px;
                font-weight: 700;
                border: none;
                padding: 10px 20px;
            }
            QPushButton:hover { background-color: #34d399; }
            QPushButton:pressed { background-color: #059669; }
        """)
        btn_push.clicked.connect(self.push_master_data_dialog)
        ps_layout.addWidget(btn_push)
        layout.addWidget(push_group)

        layout.addStretch()
        return tab

    def pull_master_data_dialog(self):
        """Pull master data from cloud using pre-configured admin credentials."""
        self.pull_thread = PullMasterDataThread(
            self.session_cloud_enrollment, self.session_cloud_pw
        )
        self.pull_thread.finished_signal.connect(self.handle_sync_result_dict)
        self.pull_thread.start()
        self.show_notification("Pulling cloud data...")

    def push_master_data_dialog(self):
        """Push all local data to cloud using pre-configured admin credentials."""
        reply = QMessageBox.question(self, "Confirm Full Sync", 
                                   "This will upload ALL your local students, routines, and departments to the cloud.\nExisting records in the cloud will be updated. Proceed?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self.push_thread = PushMasterDataThread(
                self.session_cloud_enrollment, self.session_cloud_pw
            )
            self.push_thread.finished_signal.connect(self.handle_sync_result_dict)
            self.push_thread.start()
            self.show_notification("Pushing local data to cloud...")

    def handle_sync_result_dict(self, res):
        if res.get("status") == "success":
            QMessageBox.information(self, "Sync Success", res.get("message", "Sync completed successfully!"))
            self.refresh_admin_data()
        else:
            QMessageBox.critical(self, "Sync Error", res.get("message", "Sync failed."))

    def handle_logout(self):
        self.logout_signal.emit()
        self.close()
