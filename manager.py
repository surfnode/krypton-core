import sys
import os
import subprocess
import requests
import webbrowser
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QLineEdit, QPushButton, QLabel, QProgressBar, 
    QListWidget, QComboBox, QTextEdit, QMessageBox,
    QTabWidget, QListWidgetItem
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl

TARGET_DIR = os.path.expanduser("~/.cache/llama.cpp")

class SearchWorker(QThread):
    results_ready = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, query):
        super().__init__()
        self.query = query

    def run(self):
        url = "https://huggingface.co/api/models"
        params = {
            "search": self.query,
            "filter": "gguf",
            "sort": "downloads",
            "direction": -1,
            "limit": 15
        }
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            models = [m["id"] for m in r.json()]
            self.results_ready.emit(models)
        except Exception as e:
            self.error.emit(str(e))

class FileListWorker(QThread):
    files_ready = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, repo_id):
        super().__init__()
        self.repo_id = repo_id

    def run(self):
        url = f"https://huggingface.co/api/models/{self.repo_id}/tree/main"
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            files = []
            for item in r.json():
                if item.get("path", "").endswith(".gguf"):
                    size_gb = item.get("size", 0) / (1024 ** 3)
                    files.append((item["path"], f"{item['path']} ({size_gb:.2f} GB)" if size_gb > 0 else item["path"]))
            self.files_ready.emit(files)
        except Exception as e:
            self.error.emit(str(e))

class DownloadWorker(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, repo_id, filename):
        super().__init__()
        self.repo_id = repo_id
        self.filename = filename

    def run(self):
        os.makedirs(TARGET_DIR, exist_ok=True)
        out_path = os.path.join(TARGET_DIR, self.filename)
        url = f"https://huggingface.co/{self.repo_id}/resolve/main/{self.filename}"
        
        self.log.emit(f"Connecting: {url}")
        try:
            with requests.get(url, stream=True, timeout=20) as r:
                r.raise_for_status()
                total = int(r.headers.get('content-length', 0))
                downloaded = 0
                chunk_size = 1024 * 1024

                with open(out_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                percent = int((downloaded / total) * 100)
                                self.progress.emit(percent)
            self.log.emit(f"Successfully saved to: {out_path}")
        except Exception as e:
            self.log.emit(f"Download Error: {str(e)}")
        finally:
            self.finished.emit()

class KryptonCore(QWidget):
    def __init__(self):
        super().__init__()
        self.current_files = []
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Krypton Core — Model Engine")
        self.resize(700, 560)
        main_layout = QVBoxLayout()

        self.tabs = QTabWidget()
        self.tab_discover = QWidget()
        self.tab_local = QWidget()

        self.setup_discover_tab()
        self.setup_local_tab()

        self.tabs.addTab(self.tab_discover, "Discover & Download")
        self.tabs.addTab(self.tab_local, "Local Models & Storage")
        self.tabs.currentChanged.connect(self.on_tab_switched)

        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

    def setup_discover_tab(self):
        layout = QVBoxLayout()

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search Hugging Face (e.g. qwen, mistral, abliterated)...")
        self.search_input.returnPressed.connect(self.trigger_search)
        self.btn_search = QPushButton("Search")
        self.btn_search.clicked.connect(self.trigger_search)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.btn_search)
        layout.addLayout(search_layout)

        layout.addWidget(QLabel("<b>Discovered GGUF Repositories:</b>"))
        self.repo_list = QListWidget()
        self.repo_list.itemClicked.connect(self.fetch_repo_files)
        layout.addWidget(self.repo_list)

        layout.addWidget(QLabel("<b>Available Quantizations:</b>"))
        self.file_combo = QComboBox()
        layout.addWidget(self.file_combo)

        self.btn_download = QPushButton("Download Selected Quant to Cache")
        self.btn_download.clicked.connect(self.start_download)
        layout.addWidget(self.btn_download)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(80)
        layout.addWidget(self.log_output)

        self.tab_discover.setLayout(layout)

    def setup_local_tab(self):
        layout = QVBoxLayout()

        self.storage_label = QLabel("<b>Scanning local cache...</b>")
        layout.addWidget(self.storage_label)

        self.local_list = QListWidget()
        layout.addWidget(self.local_list)

        btn_layout = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh List")
        self.btn_refresh.clicked.connect(self.refresh_local_models)
        
        self.btn_open_folder = QPushButton("Open Folder")
        self.btn_open_folder.clicked.connect(self.open_cache_folder)

        self.btn_launch = QPushButton("Launch Server (CLI & Web)")
        self.btn_launch.setStyleSheet("font-weight: bold; color: #4CAF50;")
        self.btn_launch.clicked.connect(self.launch_local_model)

        self.btn_delete = QPushButton("Delete Model")
        self.btn_delete.setStyleSheet("color: #ff5555;")
        self.btn_delete.clicked.connect(self.delete_local_model)

        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addWidget(self.btn_open_folder)
        btn_layout.addWidget(self.btn_launch)
        btn_layout.addWidget(self.btn_delete)
        layout.addLayout(btn_layout)

        self.tab_local.setLayout(layout)

    def on_tab_switched(self, index):
        if index == 1:
            self.refresh_local_models()

    def refresh_local_models(self):
        self.local_list.clear()
        if not os.path.exists(TARGET_DIR):
            self.storage_label.setText("No models cached yet.")
            return

        total_size = 0
        count = 0
        for f in sorted(os.listdir(TARGET_DIR)):
            if f.endswith(".gguf"):
                f_path = os.path.join(TARGET_DIR, f)
                size_bytes = os.path.getsize(f_path)
                total_size += size_bytes
                size_gb = size_bytes / (1024 ** 3)
                count += 1
                
                item = QListWidgetItem(f"{f}  —  [{size_gb:.2f} GB]")
                item.setData(Qt.ItemDataRole.UserRole, f)
                self.local_list.addItem(item)

        total_gb = total_size / (1024 ** 3)
        self.storage_label.setText(f"<b>Installed Models:</b> {count} | <b>Total Storage Used:</b> {total_gb:.2f} GB")

    def open_cache_folder(self):
        os.makedirs(TARGET_DIR, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(TARGET_DIR))

    def launch_local_model(self):
        selected_item = self.local_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "Selection Required", "Please select a model to launch.")
            return

        filename = selected_item.data(Qt.ItemDataRole.UserRole)
        filepath = os.path.join(TARGET_DIR, filename)

        try:
            # 1. Spawn terminal and run llama-server
            cmd = f"llama-server -m '{filepath}' --port 8080"
            shell_command = f"bash -c \"{cmd}; echo ''; echo 'Press Enter to exit...'; read\""
            subprocess.Popen(["x-terminal-emulator", "-e", shell_command])
            
            # 2. Wait 1.5 seconds for the server to bind to port 8080, then launch the browser
            QTimer.singleShot(1500, lambda: webbrowser.open("http://127.0.0.1:8080"))
            
        except Exception as e:
            QMessageBox.critical(self, "Launch Error", f"Failed to launch terminal: {str(e)}")

    def delete_local_model(self):
        selected_item = self.local_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "Selection Required", "Please select a model to delete.")
            return

        filename = selected_item.data(Qt.ItemDataRole.UserRole)
        filepath = os.path.join(TARGET_DIR, filename)

        reply = QMessageBox.question(
            self, 
            "Confirm Deletion", 
            f"Are you sure you want to permanently delete:\n\n{filename}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(filepath)
                self.refresh_local_models()
                QMessageBox.information(self, "Deleted", f"Deleted {filename} successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete model: {str(e)}")

    def trigger_search(self):
        query = self.search_input.text().strip()
        if not query:
            return
        self.btn_search.setEnabled(False)
        self.repo_list.clear()
        self.file_combo.clear()
        self.log_output.append(f"Searching Hugging Face for '{query}'...")
        
        self.search_worker = SearchWorker(query)
        self.search_worker.results_ready.connect(self.populate_repos)
        self.search_worker.error.connect(lambda err: self.log_output.append(f"Search failed: {err}"))
        self.search_worker.finished.connect(lambda: self.btn_search.setEnabled(True))
        self.search_worker.start()

    def populate_repos(self, repos):
        if not repos:
            self.log_output.append("No GGUF models found for that search query.")
            return
        self.repo_list.addItems(repos)
        self.log_output.append(f"Found {len(repos)} repositories.")

    def fetch_repo_files(self, item):
        repo_id = item.text()
        self.file_combo.clear()
        self.log_output.append(f"Fetching quants for {repo_id}...")
        
        self.file_worker = FileListWorker(repo_id)
        self.file_worker.files_ready.connect(self.populate_files)
        self.file_worker.error.connect(lambda err: self.log_output.append(f"Failed to fetch files: {err}"))
        self.file_worker.start()

    def populate_files(self, files):
        self.current_files = files
        if not files:
            self.log_output.append("No .gguf files found in repo root.")
            return
        for path, display_name in files:
            self.file_combo.addItem(display_name, path)
        self.log_output.append(f"Loaded {len(files)} quants.")

    def start_download(self):
        selected_repo_item = self.repo_list.currentItem()
        if not selected_repo_item or self.file_combo.currentIndex() < 0:
            QMessageBox.warning(self, "Selection Required", "Please choose a repository and quantization file first.")
            return

        repo_id = selected_repo_item.text()
        filename = self.file_combo.currentData()

        self.btn_download.setEnabled(False)
        self.progress_bar.setValue(0)
        
        self.dl_worker = DownloadWorker(repo_id, filename)
        self.dl_worker.progress.connect(self.progress_bar.setValue)
        self.dl_worker.log.connect(self.log_output.append)
        self.dl_worker.finished.connect(lambda: self.btn_download.setEnabled(True))
        self.dl_worker.start()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = KryptonCore()
    window.show()
    sys.exit(app.exec())
