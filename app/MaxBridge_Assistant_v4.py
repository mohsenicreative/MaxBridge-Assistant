import ctypes
import datetime
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import requests
from PySide6.QtCore import (
    QMutex,
    QMutexLocker,
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

root = None


def setup_root():
    global root
    if hasattr(sys, "frozen") and sys.frozen:
        root = Path(sys._MEIPASS)
    elif hasattr(sys, "__compiled__") and sys.__compiled__:
        try:
            root = Path(__compiled__.containing_dir)  # type: ignore
        except NameError:
            root = Path(__file__).resolve().parent
    else:
        root = Path(__file__).resolve().parent


class DownloadSignal(QObject):
    progress = Signal(int)
    status = Signal(str)
    finished = Signal(str)


class DownloadRunnable(QRunnable):
    def __init__(self, url, dest, name, expected_hash=None):
        super().__init__()
        self.url = url
        self.dest = dest
        self.name = name
        self.expected_hash = expected_hash
        self.signals = DownloadSignal()

    def run(self):
        """Main method to run the download in a thread."""
        try:
            dest_path = Path(self.dest)

            # Check if file already exists and if hash matches
            if dest_path.exists():
                local_hash = self.calculate_file_hash(dest_path)
                if self.expected_hash and local_hash == self.expected_hash:
                    self.signals.status.emit(
                        f"Skipped: {self.name} (already downloaded and verified)"
                    )
                    self.signals.progress.emit(100)
                    self.signals.finished.emit(self.name)
                    return
                else:
                    self.signals.status.emit(
                        f"Hash mismatch or file not found: {self.name}, redownloading..."
                    )

            # Start downloading the file
            self.signals.status.emit(f"Downloading: {self.name}")
            with requests.get(self.url, stream=True) as response:
                response.raise_for_status()
                total_length = int(response.headers.get("content-length", 0))
                downloaded = 0

                with dest_path.open("wb") as file:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            file.write(chunk)
                            downloaded += len(chunk)
                            percent = int(downloaded * 100 / total_length)
                            self.signals.progress.emit(percent)

            # Verify file hash after download
            if self.expected_hash:
                downloaded_hash = self.calculate_file_hash(dest_path)
                if downloaded_hash != self.expected_hash:
                    self.signals.status.emit(
                        f"Error: {self.name} - Hash mismatch after download."
                    )
                    self.signals.progress.emit(0)
                    self.signals.finished.emit(self.name)
                    return

            self.signals.status.emit(f"Completed: {self.name}")
        except Exception as e:
            self.signals.status.emit(f"Error: {self.name}: {e}")
            self.signals.progress.emit(0)
        finally:
            self.signals.finished.emit(self.name)

    def calculate_file_hash(self, file_path):
        """Calculate the SHA256 hash of a file."""
        file_path = Path(file_path)
        hash_sha256 = hashlib.sha256()
        try:
            with file_path.open("rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(byte_block)
            return hash_sha256.hexdigest()
        except Exception as e:
            self.signals.status.emit(f"Error calculating hash for {file_path}: {e}")
            return None


class MaxBridgeAssistant(QWidget):
    def __init__(self):
        super().__init__()
        self.library_prepared = False
        self.checkboxes = []
        # Use a versioned JSON endpoint for future compatibility
        self.json_url = "https://github.com/mohseni-mr/MaxBridge-Assistant/raw/refs/heads/main/resources/download_urls_v2.json"
        self.plugin_version = None
        self.megascans_library = None
        self.file_list = []
        self.threads = []
        self.completed_threads = []
        self.mutex = QMutex()
        self.pool = QThreadPool.globalInstance()
        self.temp_folder = self.setup_temp_folder()
        self.log_file = self.temp_folder / "process_log.txt"
        self.max_versions = self.detect_max_versions()
        if sys.platform == "win32":
            self.setWindowFlag(Qt.WindowType.MSWindowsFixedSizeDialogHint)
        self.initUI()

    def log_message(self, message, update_status=True):
        """
        Logs a message to the log file and optionally updates the status label.
        """
        try:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] {message}\n"

            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with self.log_file.open("a", encoding="utf-8") as log:
                log.write(log_entry)

            if update_status:
                self.status_label.setText(message)

        except Exception as e:
            print(f"Failed to log message: {message}. Error: {e}")

    def setup_temp_folder(self):
        temp_dir = Path(tempfile.gettempdir()) / "maxbridge_assistant_temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    def remove_attributes(self, path):
        # Removes hidden, system, and readonly attributes from the specified file or folder.

        # Constants for file attributes
        FILE_ATTRIBUTE_SYSTEM = 0x4
        FILE_ATTRIBUTE_HIDDEN = 0x2
        FILE_ATTRIBUTE_READONLY = 0x1

        try:
            attributes = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attributes == -1:
                self.log_message(f"Error: Path does not exist or access denied: {path}")
                return False

            new_attributes = (
                attributes
                & ~FILE_ATTRIBUTE_SYSTEM
                & ~FILE_ATTRIBUTE_HIDDEN
                & ~FILE_ATTRIBUTE_READONLY
            )
            result = ctypes.windll.kernel32.SetFileAttributesW(
                str(path), new_attributes
            )

            if result:
                return True
            else:
                return False

        except Exception as e:
            self.log_message(f"Error while updating attributes for {path}: {e}")
            return False

    def ensure_local_appdata_attributes(self):
        # Ensure that the required directories have appropriate attributes.
        local_app_data = Path(os.getenv("LOCALAPPDATA"))
        if not local_app_data:
            self.log_message("Error: LOCALAPPDATA environment variable not found.")
            return

        autodesk_folder = local_app_data / "Autodesk"
        autodesk_3dsMax_folder = autodesk_folder / "3dsMax"

        paths_to_process = [local_app_data, autodesk_folder, autodesk_3dsMax_folder]

        for path in paths_to_process:
            if path.exists():
                self.remove_attributes(path)
            else:
                self.log_message(f"Skipping: {path} (Path not found)")

        if autodesk_3dsMax_folder.exists():
            for item in autodesk_3dsMax_folder.rglob("*"):
                self.remove_attributes(item)

    def detect_max_versions(self):
        max_versions_dir = Path(os.getenv("LOCALAPPDATA")) / "Autodesk" / "3dsMax"
        if not max_versions_dir.exists():
            return []

        return sorted(
            folder.name for folder in max_versions_dir.iterdir() if folder.is_dir()
        )

    def initUI(self):
        # Get the current screen where the app is running
        screen = QApplication.primaryScreen()
        dpi = screen.logicalDotsPerInch()

        font = QFont("Segoe UI", 11)
        self.setFont(font)

        spacing = 10
        spacing_margin = 10

        self.setWindowTitle("MaxBridge Assistant")

        # Layout
        self.main_layout = QVBoxLayout()
        self.main_layout.setSpacing(spacing)
        self.main_layout.setContentsMargins(
            spacing_margin, spacing_margin, spacing_margin, spacing_margin
        )

        # 3ds Max Versions Section
        self.add_version_checkboxes()

        # Folder selection
        folder_layout = QHBoxLayout()
        self.folder_label = QLabel("Path: -", self)
        self.folder_label.setWordWrap(True)
        folder_layout.addWidget(self.folder_label)

        self.select_folder_button = QPushButton("Select Megascans Library", self)
        self.select_folder_button.clicked.connect(self.select_folder)
        folder_layout.addWidget(self.select_folder_button)
        self.main_layout.addLayout(folder_layout)

        # Process Button
        self.process_button = QPushButton("Start Setup", self)
        self.process_button.setEnabled(False)
        self.process_button.clicked.connect(self.start_process)
        self.main_layout.addWidget(self.process_button)

        # Progress Bar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: palette(base);
                border: 0;
                border-radius: 5px;
                border-style: none;
                text-align: center               
            }
            QProgressBar::chunk {
                background-color: palette(highlight);
                margin: 2px;
                border: 0;
                border-radius: 5px;
                border-style: none;
            }
        """)
        self.main_layout.addWidget(self.progress_bar)

        # Status
        self.status_label = QLabel("Status: Waiting", self)
        self.main_layout.addWidget(self.status_label)

        # Name
        self.name_label = QLabel(self)
        self.name_label.setText(
            '<a href="https://bio.mohseni.info">Mohammadreza Mohseni</a>'
        )
        self.name_label.setOpenExternalLinks(True)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setFont(QFont("Segoe UI", 10))
        self.main_layout.addWidget(self.name_label)

        self.setLayout(self.main_layout)

        self.adjustSize()
        self.setMinimumSize(480, 280)
        self.center_window()

    def add_version_checkboxes(self):
        self.max_versions_label = QLabel("Detected 3ds Max Versions:")
        self.max_versions_label.setFont(self.font())
        self.main_layout.addWidget(self.max_versions_label)

        self.max_versions_grid = QGridLayout()
        self.max_versions_grid.setSpacing(10)
        column_count = 4

        for index, version in enumerate(self.max_versions):
            checkbox = QCheckBox(version, self)
            checkbox.setChecked(True)
            checkbox.setFont(self.font())
            row = index // column_count
            col = index % column_count
            self.max_versions_grid.addWidget(checkbox, row, col)
            self.checkboxes.append(checkbox)

        self.main_layout.addLayout(self.max_versions_grid)

    def center_window(self):
        screen = QApplication.primaryScreen()
        rect = screen.availableGeometry()

        # Get the window's width and height
        window_width = self.width()
        window_height = self.height()

        # Calculate the center position
        center_x = rect.left() + (rect.width() - window_width) // 2
        center_y = rect.top() + (rect.height() - window_height) // 2

        # Move the window to the calculated position
        self.move(center_x, center_y)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Megascans Library Folder"
        )
        if folder:
            self.folder_label.setText(f"Path: {folder}")
            self.megascans_library = folder
            self.process_button.setEnabled(True)
        else:
            self.folder_label.setText("Path: -")
            self.megascans_library = None
            self.process_button.setEnabled(False)

    def start_process(self):
        if not self.megascans_library:
            self.log_message("Error: Please select a library folder.")
            return

        self.fetch_plugin_version()
        self.download_files()

    def fetch_plugin_version(self):
        try:
            response = requests.get(self.json_url)
            response.raise_for_status()
            data = response.json()
            self.plugin_version = data.get("plugin_version", "unknown")
            self.log_message(f"Plugin version fetched: {self.plugin_version}")
        except Exception as e:
            self.log_message(f"Error fetching plugin version: {e}")

    def prepare_library(self):
        """
        Prepares the library by:
        1. Ensure the local AppData attributes are correct
        2. Clears plugin folders if needed
        3. Places all downloaded files according to the JSON 'destination' field
        4. Extracts ZIPs if needed
        5. Creates Quixel.ms files
        """
        if not self.plugin_version or not self.megascans_library:
            self.log_message("Error: Missing required data.")
            return

        try:
            if self.library_prepared:
                return

            self.log_message("Starting library preparation...")
            self.ensure_local_appdata_attributes()
            self.log_message(f"Folders and files attributes have been processed.")

            # Step 2: Clear plugin folders if any file destination is a plugin folder
            plugin_path = (
                Path(self.megascans_library)
                / "support"
                / "plugins"
                / "max"
                / self.plugin_version
            )
            if plugin_path.exists():
                try:
                    shutil.rmtree(plugin_path)
                except Exception as e:
                    self.log_message(f"Error removing plugin folder: {e}")
                    return

            # Step 3: Place all downloaded files
            for file_info in self.file_list:
                file_url = file_info["url"]
                file_hash = file_info.get("hash")
                file_name = file_info["name"]
                destination_template = file_info.get("destination")
                if not destination_template:
                    self.log_message(
                        f"No destination specified for {file_name}, skipping."
                    )
                    continue

                # Replace {plugin_version} in destination path
                destination_rel = destination_template.replace(
                    "{plugin_version}", self.plugin_version
                )
                destination_path = Path(self.megascans_library) / destination_rel
                source_path = self.temp_folder / Path(file_url).name

                # If ZIP, extract; else copy
                if source_path.exists():
                    if source_path.suffix == ".zip":
                        self.log_message(
                            f"Extracting ZIP file {source_path} to {destination_path.parent}"
                        )
                        destination_path.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            with zipfile.ZipFile(source_path, "r") as zip_ref:
                                zip_ref.extractall(destination_path.parent)
                            self.log_message(
                                f"Successfully extracted ZIP file to: {destination_path.parent}"
                            )
                        except zipfile.BadZipFile:
                            self.log_message(
                                f"Error: The file {source_path} is not a valid ZIP file."
                            )
                        except Exception as e:
                            self.log_message(
                                f"Error extracting ZIP file {source_path}: {e}"
                            )
                    else:
                        self.log_message(f"Copying {source_path} to {destination_path}")
                        destination_path.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            shutil.copy2(source_path, destination_path)
                            self.log_message(
                                f"Successfully copied {file_name} to: {destination_path}"
                            )
                        except Exception as e:
                            self.log_message(f"Error copying {file_name}: {e}")
                else:
                    self.log_message(f"Error: {file_name} not found in temp folder.")

            # Step 4: Create Quixel.ms files after library setup
            self.create_quixel_files()

            # Final update
            self.library_prepared = True
            self.log_message("Library preparation complete!")

        except Exception as e:
            self.log_message(f"Error during library preparation: {e}")

    def remove_quixel_files(self, directory):
        # Remove all variations of the file "Quixel.ms" (case-insensitive) from the given directory.
        try:
            dir_path = Path(directory)
            if not dir_path.exists() or not dir_path.is_dir():
                self.log_message(f"Directory not found or invalid: {directory}")
                return

            for file in dir_path.iterdir():
                if file.is_file() and file.name.lower() == "quixel.ms":
                    try:
                        file.unlink()
                        self.log_message(f"Removed: {file}")
                    except Exception as e:
                        self.log_message(f"Failed to remove {file}: {e}")
        except Exception as e:
            self.log_message(f"Error accessing directory {directory}: {e}")

    def create_quixel_files(self):
        base_dir = Path(os.getenv("LOCALAPPDATA")) / "Autodesk" / "3dsMax"
        selected_versions = [cb.text() for cb in self.checkboxes if cb.isChecked()]

        # Step 1: Remove old Quixel.ms files
        self.log_message("Cleaning up old Quixel.ms files...")
        for version_dir in base_dir.iterdir():
            if version_dir.is_dir():
                for lang_dir in version_dir.iterdir():
                    lang_path = lang_dir / "scripts" / "startup"
                    self.remove_quixel_files(lang_path)

        # Step 2: Create new Quixel.ms files for selected versions
        self.log_message("Creating new Quixel.ms files...")
        for version in selected_versions:
            version_path = base_dir / version
            if not version_path.exists():
                self.log_message(f"Skipped: {version} (Folder not found)")
                continue

            for lang_dir in version_path.iterdir():
                lang_path = lang_dir / "scripts" / "startup"
                try:
                    lang_path.mkdir(parents=True, exist_ok=True)

                    # Build the target path using standard backslashes for the MAXScript string literal
                    target_script_path = os.path.join(
                        self.megascans_library,
                        "support",
                        "plugins",
                        "max",
                        self.plugin_version,
                        "MSLiveLink",
                        "MS_API.py",
                    ).replace("/", "\\")

                    # Modernized 3ds Max Cross-Version Macro Content
                    # Uses the native Max python.ExecuteFile utility which handles namespaces flawlessly
                    file_content = f'python.ExecuteFile @"{target_script_path}"'

                    file_path = lang_path / "Quixel.ms"
                    file_path.write_text(file_content, encoding="utf-8")

                    self.log_message(f"Created: {file_path}")
                except Exception as e:
                    self.log_message(f"Error in {lang_path}: {e}")

    def download_files(self):
        # Download files as specified in the JSON file.
        try:
            self.library_prepared = False
            self.threads = []
            self.completed_threads = []

            response = requests.get(self.json_url)
            if response.status_code != 200:
                self.log_message(f"Failed to load download URLs")
                response.raise_for_status()

            data = response.json()
            self.file_list = data.get("files", [])

            for file_info in self.file_list:
                file_url = file_info["url"]
                file_name = file_info["name"]
                file_hash = file_info.get("hash")
                file_path = self.temp_folder / Path(file_url).name

                thread = DownloadRunnable(file_url, file_path, file_name, file_hash)
                self.threads.append(thread)
                thread.signals.progress.connect(self.update_progress)
                thread.signals.status.connect(self.update_status)
                thread.signals.finished.connect(self.handle_download_complete)
                self.pool.start(thread)

        except Exception as e:
            self.log_message(f"Error downloading files: {e}")

        except Exception as e:
            self.log_message(f"Error downloading files: {e}")

    def handle_download_complete(self, name):
        # Handle the completion of each download.
        if name not in self.completed_threads:
            self.completed_threads.append(name)
            self.log_message(
                f"Completed threads: {len(self.completed_threads)} / {len(self.threads)}"
            )

        # Check if all threads are completed
        if len(self.completed_threads) == len(self.threads):
            if not self.library_prepared:
                self.log_message("All downloads completed. Preparing the library...")
                QApplication.processEvents()
                self.prepare_library()

        elif len(self.completed_threads) < len(self.threads):
            self.log_message(
                f"{len(self.threads) - len(self.completed_threads)} threads are still running, waiting for completion..."
            )

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_status(self, message):
        self.log_message(f"Status: {message}")


if __name__ == "__main__":
    setup_root()

    app = QApplication(sys.argv)

    icon_path = str(root / "resources" / "mohseni.ico")
    app.setWindowIcon(QIcon(icon_path))

    window = MaxBridgeAssistant()
    window.show()
    sys.exit(app.exec())
