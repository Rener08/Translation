#!/usr/bin/env python3
import sys
import json
import os
import subprocess
import time
import traceback
import faulthandler
import html
from datetime import datetime
import requests
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QProgressBar,
    QTextEdit, QMessageBox, QFrame, QFileDialog, QScrollArea,
    QStackedWidget, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon, QTextCursor, QTextBlockFormat, QCloseEvent

BACKEND_HEALTH_PATH = "/health"
DEFAULT_BACKEND_CANDIDATES = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:8002",
    "http://localhost:8002",
]
_RESOLVED_BACKEND_URL = None
CRASH_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "desktop_crash.log")


def _append_crash_log(title: str, detail: str) -> None:
    try:
        with open(CRASH_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] {title}\n")
            handle.write(detail.rstrip() + "\n")
    except Exception:
        pass


def _install_global_exception_hook() -> None:
    original_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_traceback):
        formatted = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        _append_crash_log("Unhandled exception", formatted)
        try:
            QMessageBox.critical(
                None,
                "程序异常",
                "GUI 遇到未处理异常，详情已写入 desktop_crash.log。",
            )
        except Exception:
            pass
        original_hook(exc_type, exc_value, exc_traceback)

    sys.excepthook = _hook


def _install_fault_handler() -> None:
    try:
        crash_file = open(CRASH_LOG_PATH, "a", encoding="utf-8")
        faulthandler.enable(file=crash_file, all_threads=True)
    except Exception:
        pass


def _candidate_backend_urls():
    configured = (
        os.getenv("DESKTOP_BACKEND_URL")
        or os.getenv("NEXT_PUBLIC_API_BASE_URL")
        or ""
    ).strip().rstrip("/")
    if configured:
        return [configured, *[url for url in DEFAULT_BACKEND_CANDIDATES if url != configured]]
    return list(DEFAULT_BACKEND_CANDIDATES)


def resolve_backend_base_url(force_probe=False):
    global _RESOLVED_BACKEND_URL

    if _RESOLVED_BACKEND_URL and not force_probe:
        return _RESOLVED_BACKEND_URL

    for base_url in _candidate_backend_urls():
        try:
            response = requests.get(f"{base_url}{BACKEND_HEALTH_PATH}", timeout=2)
            if response.status_code == 200:
                _RESOLVED_BACKEND_URL = base_url
                return base_url
        except Exception:
            continue

    raise RuntimeError(
        "Cannot connect to backend API. Start backend on port 8000 or 8002, "
        "or set DESKTOP_BACKEND_URL."
    )


class WorkerThread(QThread):
    progress = pyqtSignal(int, str)
    result = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(
        self,
        backend_url,
        url,
        provider,
        source_mode,
        api_key,
        model,
        skill_prompt="",
    ):
        super().__init__()
        self.backend_url = backend_url
        self.url = url
        self.provider = provider
        self.source_mode = source_mode
        self.api_key = api_key
        self.model = model
        self.skill_prompt = skill_prompt

    def run(self):
        try:
            self.progress.emit(10, "正在处理（下载/转录/翻译/改写）...")

            translation_config = {"provider": self.provider}
            if self.api_key:
                translation_config["api_key"] = self.api_key
            if self.model:
                translation_config["model"] = self.model

            resp = requests.post(
                f"{self.backend_url}/api/jobs/run",
                json={
                    "url": self.url,
                    "source_mode": self.source_mode,
                    "translation_config": translation_config
                },
                timeout=600
            )

            if resp.status_code >= 400:
                try:
                    detail = resp.json().get("detail", resp.text)
                except Exception:
                    detail = resp.text
                self.error.emit(str(detail or "jobs/run failed"))
                return

            data = resp.json()
            if not data.get("ok"):
                self.error.emit(data.get("detail", "Unknown error"))
                return

            translation = data.get("translation_zh", {})
            zh_segments = translation.get("segments", [])
            zh_text = "\n".join(
                str(item.get("translated_text", "")).strip()
                for item in zh_segments
                if str(item.get("translated_text", "")).strip()
            ).strip()

            if zh_text:
                self.progress.emit(75, "正在改写中文内容...")
                rewrite_payload = {
                    "source_text": zh_text,
                    "translation_config": translation_config,
                    "rewrite_focus": self.skill_prompt,
                }
                rewrite_resp = requests.post(
                    f"{self.backend_url}/api/content-rewrite",
                    json=rewrite_payload,
                    timeout=600,
                )
                if rewrite_resp.status_code >= 400:
                    try:
                        detail = rewrite_resp.json().get("detail", rewrite_resp.text)
                    except Exception:
                        detail = rewrite_resp.text
                    self.error.emit(str(detail or "content-rewrite failed"))
                    return
                rewrite_data = rewrite_resp.json()
                data["rewrite_zh"] = str(rewrite_data.get("rewritten_text", "")).strip()
            else:
                data["rewrite_zh"] = ""

            self.progress.emit(100, "完成!")
            self.result.emit(data)

        except requests.exceptions.Timeout:
            self.error.emit("请求超时，视频可能太长或后端忙碌")
        except requests.exceptions.ConnectionError as e:
            msg = str(e or "")
            lowered = msg.lower()
            if "remotedisconnected" in lowered or "connection aborted" in lowered:
                self.error.emit("上游模型连接被中断（RemoteDisconnected），请重试；若反复出现，请检查 API Key / base_url / 模型可用性。")
            else:
                self.error.emit(msg or "连接失败，请检查网络或后端状态")
        except Exception as e:
            self.error.emit(str(e))


class ChatWorker(QThread):
    response = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self,
        backend_url,
        question,
        content_context_id,
        transcript_en,
        translation_zh,
        chat_config,
    ):
        super().__init__()
        self.backend_url = backend_url
        self.question = question
        self.content_context_id = content_context_id
        self.transcript_en = transcript_en
        self.translation_zh = translation_zh
        self.chat_config = chat_config

    def run(self):
        try:
            payload = {"question": self.question}
            if self.content_context_id:
                payload["content_context_id"] = self.content_context_id
            else:
                payload["transcript_en"] = self.transcript_en
                payload["translation_zh"] = self.translation_zh
            if self.chat_config:
                payload["chat_config"] = self.chat_config

            resp = requests.post(
                f"{self.backend_url}/api/content-chat",
                json=payload,
                timeout=60
            )
            if resp.status_code >= 400:
                try:
                    detail = resp.json().get("detail", resp.text)
                except Exception:
                    detail = resp.text
                self.error.emit(str(detail or "content-chat failed"))
                return
            data = resp.json()
            if data.get("ok"):
                self.response.emit(data.get("answer", "无回答"))
            else:
                self.error.emit(data.get("detail", "Chat failed"))
        except Exception as e:
            self.error.emit(str(e))


class ChatTextEdit(QTextEdit):
    returnPressed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Return and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.returnPressed.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class YouTubeTranslatorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube 翻译助手")
        self.setMinimumSize(1100, 750)
        self.resize(1280, 800)
        self.current_content = None
        self.backend_url = None
        self._backend_online = False
        self._backend_bootstrap_error = ""
        self.worker = None
        self.chat_worker = None
        self.skills_dict = {}
        self.setup_ui()
        self.apply_light_theme()
        self.load_skills()
        self.check_backend()

    def load_skills(self):
        import os
        skills_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
        if not os.path.exists(skills_dir):
            return
        for file in os.listdir(skills_dir):
            if file.endswith(".md") or file.endswith(".txt"):
                path = os.path.join(skills_dir, file)
                name = os.path.splitext(file)[0]
                with open(path, "r", encoding="utf-8") as f:
                    self.skills_dict[name] = f.read()
        
        if hasattr(self, "skill_combo") and self.skills_dict:
            self.skill_combo.clear()
            self.skill_combo.addItems(list(self.skills_dict.keys()))

    def _current_rewrite_text(self) -> str:
        return self.trans_text.toPlainText().strip()

    def _start_local_backend_daemon(self) -> tuple[bool, str]:
        root_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(root_dir, "start-backend.sh")
        if not os.path.isfile(script_path):
            return False, f"未找到后端启动脚本: {script_path}"

        try:
            result = subprocess.run(
                ["/bin/bash", script_path, "--daemon"],
                cwd=root_dir,
                capture_output=True,
                text=True,
                timeout=45,
            )
        except Exception as exc:
            return False, f"自动启动后端失败: {exc}"

        output = "\n".join(
            part.strip()
            for part in [result.stdout, result.stderr]
            if part and part.strip()
        ).strip()
        if result.returncode != 0:
            return False, output or "start-backend.sh --daemon 执行失败"

        for _ in range(20):
            try:
                self.backend_url = resolve_backend_base_url(force_probe=True)
                return True, output
            except Exception:
                time.sleep(0.5)

        return False, output or "后端启动后仍未通过健康检查"

    def _set_backend_online_ui(self):
        self._backend_online = True

    def _set_backend_offline_ui(self):
        self._backend_online = False

    def apply_light_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #F8FAFD;
            }
            QWidget {
                background-color: #F8FAFD;
                color: #0F172A;
                font-family: "Google Sans", "PingFang SC", "Inter";
                font-size: 14px;
                letter-spacing: 0.2px;
            }
            #sidebar {
                background-color: #F8FAFD;
                border-right: none;
            }
            #sidebar_content {
                background-color: #F8FAFD;
            }
            QFrame {
                background-color: #FFFFFF;
                border-radius: 24px;
                border: none;
            }
            #rewrite_card {
                border-radius: 24px;
                background-color: #FFFFFF;
            }
            #rewrite_toolbar {
                background-color: transparent;
                border: none;
            }
            #rewrite_body {
                background-color: transparent;
                border: none;
            }
            #rewrite_action_btn {
                background-color: #F1F5F9;
                color: #334155;
                border: none;
                border-radius: 16px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 600;
                min-height: 32px;
            }
            #rewrite_action_btn:hover {
                background-color: #E2E8F0;
            }
            #rewrite_action_btn:disabled {
                background-color: transparent;
                color: transparent;
            }
            #no_border_frame {
                background-color: transparent;
                border: none;
                border-radius: 0px;
            }
            QLabel {
                background-color: transparent;
                color: #0F172A;
            }
            QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
                padding: 12px 16px;
                color: #0F172A;
                font-size: 14px;
                min-height: 24px;
            }
            QLineEdit:focus {
                border: 1px solid #5B6EFF;
                background-color: #F8FAFF;
            }
            QLineEdit::placeholder {
                color: #94A3B8;
            }
            QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
                padding: 10px 14px;
                color: #0F172A;
                font-size: 14px;
                min-height: 24px;
            }
            QComboBox:focus {
                border: 1px solid #5B6EFF;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #86868B;
                width: 0px;
                height: 0px;
            }
            QPushButton {
                background-color: #5B6EFF;
                color: #FFFFFF;
                border: none;
                border-radius: 16px;
                padding: 12px 24px;
                font-weight: 600;
                font-size: 15px;
            }
            QPushButton:hover {
                background-color: #4B5DE6;
            }
            QPushButton:disabled {
                background-color: #E2E8F0;
                color: #94A3B8;
            }
            #chat_card {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 24px;
            }
            #chat_composer {
                background-color: #FFFFFF;
                border: none;
                border-radius: 28px;
            }
            #chat_composer QTextEdit {
                background: transparent;
                border: none;
                padding: 4px 8px;
                font-size: 15px;
                color: #0F172A;
            }
            #chat_composer QTextEdit:focus {
                background-color: transparent;
            }
            #chat_send_btn {
                background-color: #101828;
                border-radius: 20px;
                min-width: 40px;
                max-width: 40px;
                min-height: 40px;
                max-height: 40px;
                padding: 0px;
                font-size: 18px;
                font-weight: 700;
            }
            #chat_send_btn:hover {
                background-color: #0B1220;
            }
            #chat_send_btn:disabled {
                background-color: #E2E8F0;
                color: #94A3B8;
            }
            QProgressBar {
                border: none;
                border-radius: 2px;
                background-color: #E2E8F0;
                text-align: center;
                color: transparent;
            }
            QProgressBar::chunk {
                background-color: #5B6EFF;
                border-radius: 2px;
            }
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QTextEdit {
                background-color: transparent;
                border: none;
                color: #1E293B;
                font-size: 16px;
                line-height: 1.8;
                padding: 0px;
            }
            QTextEdit::placeholder {
                color: #CBD5E1;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #CBD5E1;
                border-radius: 3px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background: #94A3B8;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.stack = QStackedWidget(central)
        main_layout.addWidget(self.stack)
        
        self.input_page = self._create_input_page()
        self.result_page = self._create_result_page()
        
        self.stack.addWidget(self.input_page)
        self.stack.addWidget(self.result_page)
        self.stack.setCurrentIndex(0)

    def _create_input_page(self):
        page = QWidget()
        page.setStyleSheet("background-color: #F8FAFD;")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        
        # Center Title
        title_layout = QVBoxLayout()
        title_label = QLabel("YouTube 翻译助手")
        title_label.setStyleSheet("font-size: 32px; font-weight: 700; color: #0F172A; background: transparent;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(title_label)
        
        layout.addStretch(2)
        layout.addLayout(title_layout)
        layout.addSpacing(40)
        
        # Input composer
        composer = QFrame()
        composer.setObjectName("chat_composer")
        composer.setMinimumHeight(60)
        composer.setMaximumWidth(800)
        composer.setStyleSheet("QFrame#chat_composer { border-radius: 30px; background-color: #FFFFFF; }")
        
        composer_layout = QHBoxLayout(composer)
        composer_layout.setContentsMargins(20, 10, 10, 10)
        composer_layout.setSpacing(12)
        
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("粘贴 YouTube 链接...")
        self.url_input.setText("https://www.youtube.com/watch?v=Mjc7vwys1vY")
        self.url_input.setStyleSheet("border: none; background: transparent; font-size: 16px;")
        self.url_input.returnPressed.connect(self.start_processing)
        
        self.run_button = QPushButton("➤")
        self.run_button.setFixedSize(40, 40)
        self.run_button.setStyleSheet("""
            QPushButton {
                background-color: #101828;
                color: #FFFFFF;
                border-radius: 20px;
                font-size: 18px;
            }
            QPushButton:hover { background-color: #0B1220; }
            QPushButton:disabled { background-color: #E2E8F0; color: #94A3B8; }
        """)
        self.run_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_button.clicked.connect(self.start_processing)
        
        composer_layout.addWidget(self.url_input, 1)
        composer_layout.addWidget(self.run_button)
        
        center_layout = QHBoxLayout()
        center_layout.addStretch()
        center_layout.addWidget(composer, 1)
        center_layout.addStretch()
        
        layout.addLayout(center_layout)
        
        # Progress Area
        prog_layout = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setMaximumWidth(800)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #86868B; font-size: 14px; background: transparent;")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        prog_center = QHBoxLayout()
        prog_center.addStretch()
        prog_layout.addWidget(self.progress_bar, 0, Qt.AlignmentFlag.AlignHCenter)
        prog_layout.addWidget(self.progress_label, 0, Qt.AlignmentFlag.AlignHCenter)
        prog_center.addLayout(prog_layout)
        prog_center.addStretch()
        
        layout.addSpacing(20)
        layout.addLayout(prog_center)
        
        layout.addStretch(2)
        
        # Bottom left gear & Settings
        self.settings_panel = self._create_settings_card()
        self.settings_panel.setVisible(False)
        self.settings_panel.setMaximumWidth(400)
        
        self.gear_btn = QPushButton("⚙️")
        self.gear_btn.setFixedSize(44, 44)
        self.gear_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                color: #475569;
                border-radius: 22px;
                font-size: 24px;
                border: 1px solid #E2E8F0;
            }
            QPushButton:hover {
                background-color: #F1F5F9;
                border-color: #CBD5E1;
            }
        """)
        self.gear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gear_btn.clicked.connect(lambda: self.settings_panel.setVisible(not self.settings_panel.isVisible()))
        
        bottom_layout = QHBoxLayout()
        bottom_left = QVBoxLayout()
        bottom_left.addWidget(self.settings_panel)
        bottom_left.addWidget(self.gear_btn, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft)
        
        bottom_layout.addLayout(bottom_left)
        bottom_layout.addStretch(1)
        
        layout.addLayout(bottom_layout)
        
        return page

    def _create_result_page(self):
        page = QWidget()
        page.setStyleSheet("background-color: #F8FAFD;")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)
        
        # Header (Back button + Action buttons on the right)
        header_layout = QHBoxLayout()
        
        back_btn = QPushButton("← 返回并新开一个")
        back_btn.setStyleSheet("""
            QPushButton {
                background-color: #E2E8F0;
                color: #334155;
                border-radius: 16px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #CBD5E1; }
        """)
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(self.go_to_input_page)
        header_layout.addWidget(back_btn)
        
        header_layout.addStretch()

        # Action Buttons moved to Header Right
        self.copy_button = QPushButton("复制内容")
        self.copy_button.setObjectName("rewrite_action_btn")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_rewrite_text)
        header_layout.addWidget(self.copy_button)

        self.export_button = QPushButton("导出为...")
        self.export_button.setObjectName("rewrite_action_btn")
        self.export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_rewrite_text)
        header_layout.addWidget(self.export_button)
        
        layout.addLayout(header_layout)
        
        # Translation/Rewrite Card
        trans_card = self._create_translation_card()
        layout.addWidget(trans_card, 3) 
        
        # Chat Card
        chat_card = self._create_chat_card()
        layout.addWidget(chat_card, 1)
        
        return page

    def go_to_input_page(self):
        self.stack.setCurrentIndex(0)
        self.reset_ui()
        self.clear_results()

    def _create_settings_card(self):
        card = QFrame()
        card.setObjectName("rewrite_card")
        card.setStyleSheet("QFrame#rewrite_card { background-color: #FFFFFF; border-radius: 16px; padding: 4px; }")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)
        card_layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel("翻译设置")
        header.setStyleSheet("font-size: 14px; font-weight: 600; color: #1D1D1F; background: transparent;")
        card_layout.addWidget(header)

        provider_row = QHBoxLayout()
        provider_row.setSpacing(8)
        provider_label = QLabel("翻译服务")
        provider_label.setStyleSheet("color: #86868B; font-size: 13px; background: transparent;")
        provider_label.setFixedWidth(70)
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["deepseek", "openai", "ollama", "lmstudio"])
        self.provider_combo.setCurrentText("deepseek")
        provider_row.addWidget(provider_label)
        provider_row.addWidget(self.provider_combo, 1)
        card_layout.addLayout(provider_row)

        skill_row = QHBoxLayout()
        skill_row.setSpacing(8)
        skill_label = QLabel("写作风格")
        skill_label.setStyleSheet("color: #86868B; font-size: 13px; background: transparent;")
        skill_label.setFixedWidth(70)
        self.skill_combo = QComboBox()
        if hasattr(self, "skills_dict") and self.skills_dict:
            self.skill_combo.addItems(list(self.skills_dict.keys()))
        else:
            self.skill_combo.addItem("默认模式")
        skill_row.addWidget(skill_label)
        skill_row.addWidget(self.skill_combo, 1)
        card_layout.addLayout(skill_row)

        source_row = QHBoxLayout()
        source_row.setSpacing(8)
        source_label = QLabel("内容来源")
        source_label.setStyleSheet("color: #86868B; font-size: 13px; background: transparent;")
        source_label.setFixedWidth(70)
        self.source_combo = QComboBox()
        self.source_combo.addItems(["字幕优先", "强制音频"])
        source_row.addWidget(source_label)
        source_row.addWidget(self.source_combo, 1)
        card_layout.addLayout(source_row)

        api_row = QHBoxLayout()
        api_row.setSpacing(8)
        api_label = QLabel("API Key")
        api_label.setStyleSheet("color: #86868B; font-size: 13px; background: transparent;")
        api_label.setFixedWidth(70)
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("粘贴 DeepSeek API Key")
        api_row.addWidget(api_label)
        api_row.addWidget(self.api_key_input, 1)
        card_layout.addLayout(api_row)

        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        model_label = QLabel("模型")
        model_label.setStyleSheet("color: #86868B; font-size: 13px; background: transparent;")
        model_label.setFixedWidth(70)
        self.model_input = QLineEdit()
        self.model_input.setText("deepseek-chat")
        model_row.addWidget(model_label)
        model_row.addWidget(self.model_input, 1)
        card_layout.addLayout(model_row)

        return card

    def _create_translation_card(self):
        card = QFrame()
        card.setObjectName("rewrite_card")
        
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(0)
        card_layout.setContentsMargins(0, 0, 0, 0)

        # Body
        body = QFrame()
        body.setObjectName("rewrite_body")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(32, 32, 32, 32)
        body_layout.setSpacing(0)

        self.trans_text = QTextEdit()
        self.trans_text.setReadOnly(True)
        self.trans_text.setPlaceholderText("处理完成后，结果或改写内容将呈现在这里...")
        
        css = """
        h1 { font-size: 24px; font-weight: bold; color: #1D1D1F; margin-top: 16px; margin-bottom: 12px; }
        h2 { font-size: 20px; font-weight: bold; color: #1D1D1F; margin-top: 16px; margin-bottom: 12px; }
        h3 { font-size: 16px; font-weight: bold; color: #1D1D1F; margin-top: 12px; margin-bottom: 8px; }
        p { font-size: 15px; color: #334155; margin-top: 0px; margin-bottom: 12px; line-height: 1.6; }
        ul { margin-top: 0px; margin-bottom: 12px; }
        li { font-size: 15px; color: #334155; line-height: 1.6; }
        """
        self.trans_text.document().setDefaultStyleSheet(css)
        
        body_layout.addWidget(self.trans_text)
        card_layout.addWidget(body, 1)

        return card

    def _create_chat_card(self):
        card = QFrame()
        card.setObjectName("chat_card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(0)
        card_layout.setContentsMargins(12, 12, 12, 12)

        composer_frame = QFrame()
        composer_frame.setObjectName("chat_composer")
        composer_layout = QHBoxLayout(composer_frame)
        composer_layout.setContentsMargins(20, 10, 10, 10)
        composer_layout.setSpacing(12)

        self.chat_input = ChatTextEdit()
        self.chat_input.setPlaceholderText("有问题，尽管问...")
        self.chat_input.setFixedHeight(80)
        self.chat_input.returnPressed.connect(self.send_chat)
        self.chat_input.setEnabled(False)
        composer_layout.addWidget(self.chat_input, 1)

        self.chat_button = QPushButton("↑")
        self.chat_button.setObjectName("chat_send_btn")
        self.chat_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chat_button.clicked.connect(self.send_chat)
        self.chat_button.setEnabled(False)
        composer_layout.addWidget(self.chat_button)

        card_layout.addWidget(composer_frame)

        return card



    def copy_rewrite_text(self):
        text = self._current_rewrite_text()
        if not text:
            QMessageBox.information(self, "复制", "当前没有可复制的改写内容。")
            return
        QApplication.clipboard().setText(text)
        self.progress_label.setText("已复制到剪贴板")

    def export_rewrite_text(self):
        text = self._current_rewrite_text()
        if not text:
            QMessageBox.information(self, "导出", "当前没有可导出的改写内容。")
            return

        default_name = f"rewrite-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出改写内容",
            os.path.join(os.path.expanduser("~"), default_name),
            "Markdown Files (*.md);;Text Files (*.txt);;HTML Files (*.html);;JSON Files (*.json)",
        )
        if not file_path:
            return

        _, ext = os.path.splitext(file_path)
        if not ext:
            if "Text Files" in selected_filter:
                ext = ".txt"
            elif "HTML Files" in selected_filter:
                ext = ".html"
            elif "JSON Files" in selected_filter:
                ext = ".json"
            else:
                ext = ".md"
            file_path = f"{file_path}{ext}"

        payload = self._build_export_content(text, ext.lower())
        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(payload)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return

        self.progress_label.setText(f"已导出: {os.path.basename(file_path)}")

    def _build_export_content(self, text: str, extension: str) -> str:
        if extension == ".txt":
            return text
        if extension == ".html":
            paragraphs = "</p><p>".join(
                html.escape(item) for item in text.split("\n\n") if item.strip()
            )
            return (
                "<!doctype html><html><head><meta charset=\"utf-8\">"
                "<title>中文改写</title></head><body><h1>中文改写</h1>"
                f"<p>{paragraphs}</p></body></html>"
            )
        if extension == ".json":
            return json.dumps(
                {
                    "title": "中文改写",
                    "source_url": self.url_input.text().strip(),
                    "exported_at": datetime.now().isoformat(timespec="seconds"),
                    "rewritten_text": text,
                },
                ensure_ascii=False,
                indent=2,
            )
        return f"# 中文改写\n\n{text}\n"

    def check_backend(self):
        try:
            self.backend_url = resolve_backend_base_url(force_probe=True)
            resp = requests.get(f"{self.backend_url}{BACKEND_HEALTH_PATH}", timeout=5)
            if resp.status_code == 200:
                self._set_backend_online_ui()
                self._backend_bootstrap_error = ""
                return
        except Exception:
            pass

        started, info = self._start_local_backend_daemon()
        if started:
            self._set_backend_online_ui()
            self._backend_bootstrap_error = ""
            return

        self.backend_url = None
        self._backend_bootstrap_error = info
        self._set_backend_offline_ui()

    def start_processing(self):
        self.check_backend()
        if not self.backend_url:
            extra = f"\n\n自动启动信息：{self._backend_bootstrap_error}" if self._backend_bootstrap_error else ""
            QMessageBox.critical(self, "错误", f"后端未连接，且自动拉起失败。{extra}")
            return

        url = self.url_input.text().strip()
        if not url:
            QMessageBox.critical(self, "错误", "请输入 YouTube 链接")
            return

        self.run_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("处理中...")
        self.clear_results()

        selected_skill = self.skill_combo.currentText()
        skill_prompt = self.skills_dict.get(selected_skill, "")
        
        self.worker = WorkerThread(
            backend_url=self.backend_url,
            url=url,
            provider=self.provider_combo.currentText(),
            source_mode="subtitle_first" if self.source_combo.currentText() == "字幕优先" else "force_audio",
            api_key=self.api_key_input.text().strip(),
            model=self.model_input.text().strip(),
            skill_prompt=skill_prompt,
        )
        self.worker.progress.connect(self.update_progress)
        self.worker.result.connect(self.display_results)
        self.worker.error.connect(self.show_error)
        self.worker.finished.connect(self.reset_ui)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def update_progress(self, value, text):
        self.progress_bar.setValue(value)
        self.progress_label.setText(text)

    def display_results(self, data):
        rewritten_text = str(data.get("rewrite_zh", "")).strip()
        if rewritten_text:
            self.trans_text.setMarkdown(rewritten_text)
        else:
            translation = data.get("translation_zh", {})
            zh_segments = translation.get("segments", [])
            if zh_segments:
                paragraphs = []
                for seg in zh_segments:
                    text = str(seg.get("translated_text", "")).strip()
                    if text:
                        paragraphs.append(text)
                self.trans_text.setMarkdown("\n\n".join(paragraphs))
            else:
                self.trans_text.setMarkdown("暂无可展示内容")

        has_rewrite = bool(self._current_rewrite_text())
        self.copy_button.setEnabled(has_rewrite)
        self.export_button.setEnabled(has_rewrite)

        self.current_content = data
        self.chat_input.setEnabled(True)
        self.chat_button.setEnabled(True)
        self.stack.setCurrentIndex(1)

    def send_chat(self):
        if not self.backend_url:
            self.check_backend()
        if not self.backend_url:
            QMessageBox.warning(self, "提示", "后端未连接，无法发送提问")
            return

        if not self.current_content:
            QMessageBox.warning(self, "提示", "请先处理一个视频")
            return

        question = self.chat_input.toPlainText().strip()
        if not question:
            return

        self.chat_input.clear()

        content_context_id = self.current_content.get("content_context_id", "")
        transcript_en = self.current_content.get("transcript_en", {}).get("text", "")
        translation_zh = "\n".join(
            seg.get("translated_text", "")
            for seg in self.current_content.get("translation_zh", {}).get("segments", [])
        )

        self.chat_button.setEnabled(False)
        self.chat_button.setText("…")

        chat_config = {
            "provider": self.provider_combo.currentText(),
        }
        api_key = self.api_key_input.text().strip()
        model = self.model_input.text().strip()
        if api_key:
            chat_config["api_key"] = api_key
        if model:
            chat_config["model"] = model

        self.chat_worker = ChatWorker(
            self.backend_url,
            question,
            content_context_id,
            transcript_en,
            translation_zh,
            chat_config,
        )
        self.chat_worker.response.connect(self.on_chat_response)
        self.chat_worker.error.connect(self.on_chat_error)
        self.chat_worker.finished.connect(self._on_chat_finished)
        self.chat_worker.finished.connect(self.chat_worker.deleteLater)
        self.chat_worker.start()

    def on_chat_response(self, answer):
        QMessageBox.information(self, "内容问答", answer)

    def on_chat_error(self, error):
        lowered = str(error or "").lower()
        if "authentication fails" in lowered or "invalid api key" in lowered or "incorrect api key" in lowered:
            QMessageBox.warning(self, "内容问答", "鉴权失败：当前 API Key 无效，请检查左侧 API Key 与 provider 是否匹配。")
            return
        QMessageBox.warning(self, "内容问答", f"对话失败：{error}")

    def _on_chat_finished(self):
        self.chat_button.setEnabled(True)
        self.chat_button.setText("↑")
        self.chat_worker = None

    def show_error(self, message):
        self._set_backend_offline_ui()
        self.progress_label.setText(f"错误: {message[:50]}")
        QMessageBox.critical(self, "处理错误", message)

    def reset_ui(self):
        self.run_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        self.worker = None

    def clear_results(self):
        self.trans_text.clear()
        self.current_content = None
        self.chat_input.setEnabled(False)
        self.chat_button.setEnabled(False)
        self.chat_input.clear()
        self.copy_button.setEnabled(False)
        self.export_button.setEnabled(False)

    def closeEvent(self, event: QCloseEvent):
        still_running = False
        for thread_name in ("worker", "chat_worker"):
            thread = getattr(self, thread_name, None)
            if thread is None:
                continue
            try:
                if thread.isRunning():
                    thread.requestInterruption()
                    thread.quit()
                    if not thread.wait(2000):
                        still_running = True
            except Exception:
                pass
            if not still_running:
                setattr(self, thread_name, None)

        if still_running:
            QMessageBox.warning(self, "请稍候", "后台任务仍在结束中，请稍后再关闭。")
            event.ignore()
            return

        super().closeEvent(event)


def main():
    _install_fault_handler()
    _install_global_exception_hook()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = YouTubeTranslatorApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
