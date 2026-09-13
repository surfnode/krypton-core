import sys
import os
import requests
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QLineEdit, QPushButton, QLabel, QProgressBar, 
    QListWidget, QComboBox, QTextEdit, QMessageBox
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt

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
        self.resize(650, 520)
        layout = QVBoxLayout()

        # Search Bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search Hugging Face (e.g. qwen abliterated, mistral nemo)...")
        self.search_input.returnPressed.connect(self.trigger_search)
        self.btn_search = QPushButton("Search")
        self.btn_search.clicked.connect(self.trigger_search)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.btn_search)
        layout.addLayout(search_layout)

        # Repositories List
        layout.addWidget(QLabel("<b>Discovered GGUF Repositories:</b>"))
        self.repo_list = QListWidget()
        self.repo_list.itemClicked.connect(self.fetch_repo_files)
        layout.addWidget(self.repo_list)

        # Quant Picker
        layout.addWidget(QLabel("<b>Available Quantizations:</b>"))
        self.file_combo = QComboBox()
        layout.addWidget(self.file_combo)

        # Download Action
        self.btn_download = QPushButton("Download Selected Quant to Cache")
        self.btn_download.clicked.connect(self.start_download)
        layout.addWidget(self.btn_download)

        # Progress & Logs
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(90)
        layout.addWidget(self.log_output)

        self.setLayout(layout)

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
        self.log_output.append(f"Fetching quantization files for {repo_id}...")
        
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
