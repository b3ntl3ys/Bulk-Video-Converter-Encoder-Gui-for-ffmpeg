import sys
import os
import re
import time
import zipfile
import urllib.request
import subprocess
from subprocess import STARTUPINFO, STARTF_USESHOWWINDOW
from datetime import datetime
from PyQt5 import QtCore
from PyQt5.QtCore import QThread
from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog, QLabel, QTableWidget, QPushButton, QComboBox, QTableWidgetItem, QLabel, \
    QWidget, QGridLayout, QHBoxLayout, QVBoxLayout, QFormLayout, QLineEdit, QTabWidget,QSizePolicy,QPlainTextEdit,QGroupBox,QAction,QMessageBox,QMenu,QProgressDialog

LIGHT_STYLE = ("""
    QMainWindow {
        background-color: #f0f0f0;
    }
    QTabWidget::pane {
        border: none;
    }
    QTabBar {
        background-color: #333;
        color: white;
        height: 30px;
    }
    QTabBar::tab:selected {
        background-color: #555;
    }
    QTabBar::tab:!selected {
        background-color: #444;
    }
    QPushButton {
        border-radius: 15px;
        background-color: #007BFF;
        color: white;
        border: none;
        padding: 8px 15px;
    }
    QPushButton:hover {
        background-color: #0056b3;
    }
    QLineEdit, QComboBox, QTableWidget, QPlainTextEdit {
        background-color: white;
        border: 1px solid #ccc;
        padding: 5px;
    }
    QMessageBox {
        background-color: #f0f0f0;
        color: #000000;
    }
    QMessageBox QPushButton {
        background-color: #e0e0e0;
        color: black;
        border: 1px solid #cccccc;
    }
    QComboBox {
        border-radius: 10px;
    }
""")

DARK_STYLE = ("""
    QMainWindow {
        background-color: #212121;
    }
    QTabWidget::pane {
        border: none;
    }
    QTabBar {
        background-color: #121212;
        color: #ffffff;
    }
    QTabBar::tab:selected {
        background-color: #424242;
    }
    QTabBar::tab:!selected {
        background-color: #1c1c1c;
    }
    QPushButton {
        border-radius: 15px;
        background-color: #0056b3;
        color: white;
        border: none;
        padding: 8px 15px;
    }
    QPushButton:hover {
        background-color: #474747;
    }
    QLineEdit, QComboBox, QPlainTextEdit {
        background-color: #1e1e1e;
        color: #ffffff;
        border: 1px solid #333333;
    }
    QComboBox {
        border-radius: 10px;
        padding: 6px 12px;
    }
    QTableWidget {
        background-color: #1e1e1e;
        color: #ffffff;
    }
    QTableWidget QHeaderView::section {
        background-color: #333333;
        color: #ffffff;
    }
    QLabel ,QGroupBox{
        color: #ffffff;
    }
    QMessageBox {
        background-color: #212121;
        color: #ffffff;
    }
    QMessageBox QPushButton {
        background-color: #333333;
        color: white;
        border: 1px solid #444444;
    }
""")

bitrate_num = "1M","2M","3M","4M","5M","6M","8M","10M","12M","14M","20M","30M","40M","50M"
sel_preset = "slow", "medium", "fast"
num_encodes = "1", "2", "3","4","5"
mp4_output = ".mp4"
mkv_output = ".mkv"
def get_video_duration(video_file):
    """Get the duration of a video using FFprobe."""
    command = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_file]
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        output = subprocess.check_output(command, universal_newlines=True, startupinfo=startupinfo)
        return float(output.strip())
    except subprocess.CalledProcessError as e:
        print(f"Error getting video duration for {video_file}: {e}")
        return None
    
from concurrent.futures import ThreadPoolExecutor

class VideoEncoderThread(QThread):
    fps_updated = QtCore.pyqtSignal(int, float)
    encoding_canceled = QtCore.pyqtSignal()
    elapsed_time_updated = QtCore.pyqtSignal(str)
    encoding_complete = QtCore.pyqtSignal()
    encoding_progress_updated = QtCore.pyqtSignal(int, str)  # New signal for encoding progress
    encoding_completed = QtCore.pyqtSignal(int)
    console_output_updated = QtCore.pyqtSignal(str)  # New signal for console output

    def __init__(self, input_files, output_folder, preset, bitrate, simultaneous_encodes, hwaccel_index, bitrate_mode_combobox,min_bitrate,max_bitrate,format_combobox):
        super().__init__()
        self.input_files = input_files
        self.output_folder = output_folder
        self.preset = preset
        self.bitrate = bitrate
        self.simultaneous_encodes = simultaneous_encodes
        self.bitrate_mode_combobox = bitrate_mode_combobox  # Store the bitrate_mode_combobox as an instance variable
        self.min_bitrate_combobox = min_bitrate
        self.max_bitrate_combobox = max_bitrate
        self.format_combobox = format_combobox
        self.processes = []
        self.elapsed_times = [0] * len(input_files)
        self.start_times = [num_encodes] * len(input_files)
        self._is_canceled = False
        self.hwaccel_index = hwaccel_index
        self.started_encoding = [False] * len(input_files)
        self.finished_encoding = [False] * len(input_files)
        self.processed_frames = [0] * len(input_files)

    def run(self):
        with ThreadPoolExecutor(max_workers=self.simultaneous_encodes) as executor:
            futures = []

            for i, input_file in enumerate(self.input_files):
                # Choose format based on combobox selection
                selected_format = self.format_combobox.currentText()
                print(selected_format)

                # Modify the output file name to include the selected format
                output_file = os.path.splitext(os.path.join(self.output_folder, os.path.basename(input_file)))[0] + '.' + selected_format


                # Get the selected hardware acceleration option based on the index
                hwaccel_options = ["Nvidia_Cuda_h264","Nvidia_Cuvid_h264","Nvidia_Cuda_265", "Nvidia_Cuvid_265"]
                if 0 <= self.hwaccel_index < len(hwaccel_options):
                    hwaccel = hwaccel_options[self.hwaccel_index]
                else:
                    hwaccel = "auto"

                if hwaccel  == "Nvidia_Cuvid_265":
                    command = [
                        "ffmpeg",
                        "-y",
                        "-hwaccel", "cuvid",
                        "-i", input_file,
                        "-c:v", "hevc_nvenc",
                        "-preset", self.preset,
                    ]
                    
                    if self.bitrate_mode_combobox.currentText() == "CBR":
                        command += ["-b:v", self.bitrate]
                    elif self.bitrate_mode_combobox.currentText() == "VBR":
                        command += ["-b:v",self.min_bitrate_combobox.currentText(),"-minrate", self.min_bitrate_combobox.currentText(), "-maxrate", self.max_bitrate_combobox.currentText(), "-bufsize", "50M"]
                    
                    command += ["-c:a", "copy", output_file]

                if hwaccel  == "Nvidia_Cuvid_h264":
                    command = [
                        "ffmpeg",
                        "-y",
                        "-hwaccel", "cuvid",
                        "-i", input_file,
                        "-c:v", "h264_nvenc",
                        "-preset", self.preset,
                        ]
                    
                    if self.bitrate_mode_combobox.currentText() == "CBR":
                        command += ["-b:v", self.bitrate]
                    elif self.bitrate_mode_combobox.currentText() == "VBR":
                        command += ["-b:v",self.min_bitrate_combobox.currentText(),"-minrate", self.min_bitrate_combobox.currentText(), "-maxrate", self.max_bitrate_combobox.currentText(), "-bufsize", "50M"]
                    
                    command += ["-c:a", "copy", output_file]

                if hwaccel == "Nvidia_Cuda_265":
                    command = [
                        "ffmpeg",
                        "-y",
                        "-hwaccel", "cuda",
                        "-i", input_file,
                        "-c:v", "hevc_nvenc",
                        "-preset", self.preset,
                        ]
                    
                    if self.bitrate_mode_combobox.currentText() == "CBR":
                        command += ["-b:v", self.bitrate]
                    elif self.bitrate_mode_combobox.currentText() == "VBR":
                        command += ["-b:v",self.min_bitrate_combobox.currentText(),"-minrate", self.min_bitrate_combobox.currentText(), "-maxrate", self.max_bitrate_combobox.currentText(), "-bufsize", "50M"]
                   
                    command += ["-c:a", "copy", output_file]

                if hwaccel == "Nvidia_Cuda_h264":
                    command = [
                        "ffmpeg",
                        "-y",
                        "-hwaccel", "cuda",
                        "-i", input_file,
                        "-c:v", "h264_nvenc",
                        "-preset", self.preset,
                        ]
                    
                    if self.bitrate_mode_combobox.currentText() == "CBR":
                        command += ["-b:v", self.bitrate]
                    elif self.bitrate_mode_combobox.currentText() == "VBR":
                        command += ["-b:v",self.min_bitrate_combobox.currentText(),"-minrate", self.min_bitrate_combobox.currentText(), "-maxrate", self.max_bitrate_combobox.currentText(), "-bufsize", "50M"]
                    
                    command += ["-c:a", "copy", output_file]

                future = executor.submit(self.execute_ffmpeg, command, i)
                futures.append(future)

            for i, future in enumerate(futures):
                future.result()

                if self._is_canceled:
                    self.encoding_canceled.emit()

                else:
                    self.encoding_completed.emit(i)  # Emit the signal with the row index
                    
                   

    def shutdown(self):
        self._is_canceled = True
        # Terminate all subprocesses
        for process in self.processes:
            process.terminate()
            process.wait()

    def cancel_encoding(self):
        self._is_canceled = True
        self.shutdown()

    def execute_ffmpeg(self, command, row_index):
        startupinfo = STARTUPINFO()
        startupinfo.dwFlags |= STARTF_USESHOWWINDOW
        try:
            # Process the FFmpeg command and capture the output
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
                startupinfo=startupinfo,
                encoding='utf-8',  # Specify encoding directly
                errors='replace',  # Handle decoding errors
                text=True  # Use text mode
            )

            self.processes.append(process)
            self.start_times[row_index] = datetime.now()
            while True:
                line = process.stdout.readline()
                if not line:
                    break

                if self._is_canceled:
                    break

                # Start the elapsed timer only when encoding has started for the video item
                if not self.started_encoding[row_index]:
                    self.started_encoding[row_index] = True
                    self.start_times[row_index] = datetime.now()

                fps_match = re.search(r'(\d+\.?\d*)\sfps', line)
                if fps_match:
                    fps = float(fps_match.group(1))
                    elapsed_time = (datetime.now() - self.start_times[row_index]).total_seconds()
                    if elapsed_time > 0:
                        fps = fps / elapsed_time
                    self.fps_updated.emit(row_index, fps)

                if self.started_encoding[row_index]:
                    self.elapsed_times[row_index] = int((datetime.now() - self.start_times[row_index]).total_seconds())

                # Emit the console output line directly to the main GUI
                self.console_output_updated.emit(line.strip())  # Emitting the stripped output line

                frame_match = re.search(r'frame=\s*(\d+)', line)
                if frame_match:
                    self.processed_frames[row_index] = int(frame_match.group(1))

            process.wait()

            # Emit a signal indicating the task for row_index is completed
            self.encoding_completed.emit(row_index)

        except Exception as e:
            # Handle exceptions (e.g., log the error)
            print(f"An error occurred: {e}")
        
    def get_processed_frames(self, row):
        # Return the number of processed frames for the task at the specified row
        return self.processed_frames[row]

class VideoEncoder(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.is_dark_mode = True  # Start with dark mode enabled
        self.setStyleSheet(DARK_STYLE)  

        self.setWindowTitle("Video Encoder")
        self.setGeometry(100, 100, 1000, 800)

        self.init_ui()
        self.check_and_install_ffmpeg()


    def download_and_install_ffmpeg(self):
        print("Downloading FFmpeg...")

        # New download URL
        download_url = "hhttps://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

        # Rest of the code remains the same
        download_path = os.path.join(os.getcwd(), "ffmpeg.zip")

        # Create a progress dialog
        progress_dialog = QProgressDialog("Downloading FFmpeg...", "Cancel", 0, 100)
        progress_dialog.setWindowModality(QtCore.Qt.WindowModal)
        progress_dialog.setWindowTitle("Download Progress")
        progress_dialog.setAutoClose(True)

        def reporthook(blocknum, blocksize, totalsize):
            nonlocal progress_dialog

            # Calculate the download progress
            progress = min(int(blocknum * blocksize * 100 / totalsize), 100)

            # Update the progress dialog
            progress_dialog.setValue(progress)

        urllib.request.urlretrieve(download_url, download_path, reporthook=reporthook)

        # Close the progress dialog
        progress_dialog.close()

        print("Extracting FFmpeg...")

        # Extract the downloaded zip file directly to C:\ffmpeg\bin
        ffmpeg_bin_path = "C:\\ffmpeg\\bin"

        with zipfile.ZipFile(download_path, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                try:
                    file_info.filename = os.path.basename(file_info.filename)  # Get only the filename
                    zip_ref.extract(file_info, ffmpeg_bin_path)
                except Exception as e:
                    #print(f"Error extracting file: {file_info.filename}")
                    #print(f"Exception: {e}")
                    continue


        # Clean up: remove the downloaded zip file
        os.remove(download_path)

        # Add the FFmpeg bin directory to the system's PATH
        self.add_to_path(ffmpeg_bin_path)

        # Print a message
        print("FFmpeg installed successfully.")


    def check_and_install_ffmpeg(self): 
        if not self.is_ffmpeg_installed():
            message = (
                "FFmpeg is not installed or not found in the system's PATH.\n\n"
                "FFmpeg is required for this application to function properly. "
                "Do you want to download and install it to 'C:\\ffmpeg\\bin'?"
            )

            reply = QMessageBox.question(self, 'FFmpeg Not Found', message,
                                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

            if reply == QMessageBox.Yes:
                self.download_and_install_ffmpeg()
                print("FFmpeg installed successfully.")
            else:
                print("User chose not to install FFmpeg.")
                # Handle the case where the user chooses not to install FFmpeg

    def is_ffmpeg_installed(self):
        try:
            # Use subprocess to run the command 'ffmpeg -version'
            subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            print("FFmpeg is already installed.")
            return True
        except FileNotFoundError:
            print("FFmpeg is not installed.")
            return False
        
    def add_to_path(self, program_path: str):
        """Takes in a path to a program and adds it to the user-specific path"""
        if os.name == "nt":  # Windows systems
            import winreg  # Allows access to the windows registry
            import ctypes  # Allows interface with low-level C API's

            with winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER) as root:  # Get the current user registry
                with winreg.OpenKey(root, "Environment", 0, winreg.KEY_ALL_ACCESS) as key:  # Go to the environment key
                    existing_path_value = winreg.QueryValueEx(key, "PATH")[0]  # Grab the current path value

                    # Check if the path is already in the existing value
                    if program_path not in existing_path_value:
                        new_path_value = existing_path_value + ";" + program_path
                        winreg.SetValueEx(key, "PATH", 0, winreg.REG_EXPAND_SZ, new_path_value)  # Update the path

                # Tell other processes to update their environment
                HWND_BROADCAST = 0xFFFF
                WM_SETTINGCHANGE = 0x1A
                SMTO_ABORTIFHUNG = 0x0002
                result = ctypes.c_long()
                SendMessageTimeoutW = ctypes.windll.user32.SendMessageTimeoutW
                SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, u"Environment", SMTO_ABORTIFHUNG, 5000, ctypes.byref(result), )
        else:  # If the system is *nix
            print("This method is intended for Windows systems. For *nix systems, consider modifying the PATH manually.")

        print(f"Added {program_path} to user path, please restart the shell for changes to take effect")



    def contextMenuEvent(self, event):
        # Ensure the event is within the bounds of the QTableWidget
        if not self.table_widget.underMouse():
            return

        contextMenu = QMenu(self)
        
        # Map the event position to the viewport of the table widget
        tablePos = self.table_widget.viewport().mapFromGlobal(event.globalPos())
        row = self.table_widget.rowAt(tablePos.y())

        # Add 'Delete Row' action if the click is on a valid row
        deleteAction = None
        if row >= 0:
            # Optionally select the row that was right-clicked
            self.table_widget.selectRow(row)

            deleteAction = contextMenu.addAction("Remove Selected")

        # Add 'Remove All' action
        removeAllAction = contextMenu.addAction("Remove All")

        action = contextMenu.exec_(event.globalPos())

        if action == deleteAction and deleteAction is not None:
            self.delete_row(row)
        elif action == removeAllAction:
            self.remove_all_rows()

    def delete_row(self, row):
        # Confirm before deleting
        reply = QMessageBox.question(self, 'Remove Selected', 'Are you sure you want to delete this row?', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.table_widget.removeRow(row)

    def remove_all_rows(self):
        # Confirm before removing all rows
        reply = QMessageBox.question(self, 'Remove All Rows', 'Are you sure you want to remove all rows?', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.table_widget.setRowCount(0)

    def toggle_theme(self):
        if self.is_dark_mode:
            self.setStyleSheet(LIGHT_STYLE)
            self.is_dark_mode = False
        else:
            self.setStyleSheet(DARK_STYLE)
            self.is_dark_mode = True

    def reset_ui(self):
       
        self.input_button.setEnabled(True)
        self.output_button.setEnabled(True)
        self.output_textbox.setEnabled(True)
        self.preset_combobox.setEnabled(True)
        self.bitrate_combobox.setEnabled(True)
        self.hwaccel_combobox.setEnabled(True)
        self.Simultaneous_Encodes_combobox.setEnabled(True)
        self.encode_button.setEnabled(True)
        self.cancel_button.setEnabled(True)

    def init_ui(self):

        self.input_folder = ''
        self.settings = QSettings("MyCompany", "VideoEncoder")
        self.input_folder = self.settings.value("input_folder", "")
        self.output_folder = self.settings.value("output_folder", "")
        main_widget = QWidget(self)
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        # Set tab position to top (optional, in case it was changed elsewhere)
        self.tab_widget.setTabPosition(QTabWidget.North)
        self.tab1 = QWidget()
        self.tab2 = QWidget()
        self.tab_widget.addTab(self.tab1, "Encoder")
        self.tab_widget.addTab(self.tab2, "Console")
        self.init_tab1_ui()
        self.init_tab2_ui()
        #Create the menu bar and menus as instance variables
        self.menubar = self.menuBar()
        self.file_menu = self.menubar.addMenu("File")
        self.help_menu = self.menubar.addMenu("Help")
        # Create actions for the menu items as instance variables
        self.theme_action = QAction("Toggle Dark/Light Mode", self)
        self.theme_action.triggered.connect(self.toggle_theme)
        self.file_menu.addAction(self.theme_action)
        self.open_action = QAction("Open", self)
        self.open_action.triggered.connect(self.select_input_files)
        self.file_menu.addAction(self.open_action)
        self.exit_action = QAction("Exit", self)
        self.exit_action.triggered.connect(self.close)
        self.file_menu.addAction(self.exit_action)
        self.about_action = QAction("About", self)
        self.about_action.triggered.connect(self.show_about_dialog)
        self.help_menu.addAction(self.about_action)

    def init_tab1_ui(self):
        layout = QVBoxLayout(self.tab1)
    
        input_group = QGroupBox("Input", self.tab1)
        form_layout = QFormLayout(input_group)

        self.input_button = QPushButton("Select Files", self.tab1)
        form_layout.addRow("Files:", self.input_button)
        self.table_widget = QTableWidget(self.tab1)
        self.table_widget.setColumnCount(5)  
        self.table_widget.setHorizontalHeaderLabels(["Input File", "Elapsed Time", "FPS", "Time Remaining", "Status"])
        output_group = QGroupBox("Output", self.tab1)
        form_layout = QFormLayout(output_group)
        self.output_textbox = QLineEdit(self.tab1)
        self.output_button = QPushButton("Select Folder", self.tab1)
        form_layout.addRow("Folder:", self.output_textbox)
        form_layout.addRow("", self.output_button)
        settings_group = QGroupBox("Settings", self.tab1)
        grid_layout = QGridLayout(settings_group)
        self.Simultaneous_Encodes_combobox = QComboBox(self.tab1)
        self.bitrate_combobox = QComboBox(self.tab1)
        self.preset_combobox = QComboBox(self.tab1)
        self.format_combobox = QComboBox(self.tab1)
        self.format_combobox.addItems(["mp4", "mkv"])
        self.hwaccel_combobox = QComboBox(self.tab1)
        self.hwaccel_combobox.addItems(["Nvidia_Cuda_h264", "Nvidia_Cuvid_h264","Nvidia_cuda_265","Nvidia_Cuvid_265"])
        grid_layout.addWidget(QLabel("Simultaneous Encodes:"), 0, 0)
        grid_layout.addWidget(self.Simultaneous_Encodes_combobox, 0, 1)
        grid_layout.addWidget(QLabel("Bitrate:"), 1, 2)
        grid_layout.addWidget(self.bitrate_combobox, 1 ,3)
        grid_layout.addWidget(QLabel("Preset:"), 1, 0)
        grid_layout.addWidget(self.preset_combobox, 1, 1)
        grid_layout.addWidget(QLabel("Format:"), 3,0)
        grid_layout.addWidget(self.format_combobox,3,1)
    
        grid_layout.addWidget(QLabel("Hardware Acceleration:"), 4, 0)
        grid_layout.addWidget(self.hwaccel_combobox, 4, 1)
        self.encode_button = QPushButton("Encode Videos", self.tab1)
        self.cancel_button = QPushButton("Cancel Encode", self.tab1)
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.encode_button)
        button_layout.addWidget(self.cancel_button)
        layout.addWidget(input_group)
        layout.addWidget(self.table_widget)
        layout.addWidget(output_group)
        layout.addWidget(settings_group)
        layout.addLayout(button_layout)

        # New Bitrate Mode Combobox
        self.bitrate_mode_combobox = QComboBox(self.tab1)
        self.bitrate_mode_combobox.addItems(["CBR", "VBR"])
        grid_layout.addWidget(QLabel("Bitrate Mode:"), 0, 2)
        grid_layout.addWidget(self.bitrate_mode_combobox, 0, 3)
        self.bitrate_mode_combobox.currentIndexChanged.connect(self.on_bitrate_mode_change)


        # Min Bitrate Editable Combobox
        self.min_bitrate_combobox = QComboBox(self.tab1)
        self.min_bitrate_combobox.setEditable(True)
        grid_layout.addWidget(QLabel("Min Bitrate (M):"), 3, 2)
        grid_layout.addWidget(self.min_bitrate_combobox, 3, 3)

        # Max Bitrate Editable Combobox
        self.max_bitrate_combobox = QComboBox(self.tab1)
        self.max_bitrate_combobox.setEditable(True)
        grid_layout.addWidget(QLabel("Max Bitrate (M):"), 4, 2)
        grid_layout.addWidget(self.max_bitrate_combobox, 4, 3)

        self.bitrate_combobox.addItems(bitrate_num)
        self.min_bitrate_combobox.addItems(bitrate_num)
        self.max_bitrate_combobox.addItems(bitrate_num)


        self.preset_combobox.addItems(sel_preset)
        self.Simultaneous_Encodes_combobox.addItems(num_encodes)
        # Read previous settings using QSettings
        self.settings = QSettings("MyCompany", "VideoEncoder")
        previous_bitrate = self.settings.value("bitrate", "1M")
        previous_bitrate_mode = self.settings.value("bitrate_mode", "CBR")
        previous_min_bitrate = self.settings.value("min_bitrate", "1M")
        previous_max_bitrate = self.settings.value("max_bitrate", "2M")
        previous_preset = self.settings.value("preset", "medium")
        previous_simultaneous_encodes = self.settings.value("simultaneous_encodes", "1")
        previous_hwaccel_index = int(self.settings.value("hwaccel_index", "0"))
        previous_output_folder = self.settings.value("output_folder", "")
        # Create and set default values for comboboxes
        self.bitrate_combobox.setCurrentText(previous_bitrate)
        self.bitrate_mode_combobox.setCurrentText(previous_bitrate_mode)
        self.min_bitrate_combobox.setCurrentText(previous_min_bitrate)
        self.max_bitrate_combobox.setCurrentText(previous_max_bitrate)

        self.preset_combobox.setCurrentText(previous_preset)
        self.Simultaneous_Encodes_combobox.setCurrentText(previous_simultaneous_encodes)
        self.hwaccel_combobox.setCurrentIndex(previous_hwaccel_index)
        self.output_textbox.setText(previous_output_folder)
        self.input_button.clicked.connect(self.select_input_files)
        self.output_button.clicked.connect(self.select_output_folder)
        self.encode_button.clicked.connect(self.encode_videos)
        self.start_time = None
        self.total_video_duration = 0
        self.simultaneous_encodes = 0
        self.fps_queue = []
        self.frame_count_queue = []
        self.current_fps = 25
        self.timer = QtCore.QTimer(self)
        self.cancel_button.setEnabled(False)  # Initially disable the cancel button

        


    def init_tab2_ui(self):
        layout = QVBoxLayout(self.tab2)
        label2 = QLabel("Console", self.tab2)
        layout.addWidget(label2)
        # Adding a QPlainTextEdit that expands to fill the available space in Tab 2
        self.line_edit_tab2 = QPlainTextEdit(self.tab2)  # Use QPlainTextEdit instead of QLineEdit
        size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.line_edit_tab2.setSizePolicy(size_policy)
        layout.addWidget(self.line_edit_tab2)

    @QtCore.pyqtSlot(str)
    def update_console_output(self, line):
        self.line_edit_tab2.appendPlainText(line)  # Use appendPlainText to add new lines


    def show_about_dialog(self):
        about_text = (
            "Simple Video Encoder/Converter for Nvidia GPUs\n"

            "Tested on Nvidia 3060, 3070, 4090\n\n"

            "Note: This application is a work in progress, and not all functions work correctly.\n\n"

            "Version: 4.0\n\n"

            "Key Features:\n"

            "GUI Interface for easy interaction\n"

            "Hardware Acceleration for faster encoding (Cuvid, Cuda)\n"

            "Concurrent Video Encoding for improved efficiency\n"

            "Live Encoding Progress display with Elapsed Time, FPS, and Time Remaining\n"

            "Customizable encoding settings (bitrate, preset, h264, hevc 265)\n\n"

            "ffmpeg commands are:\n\n"

            "Nvidia Cuda\n"
            "ffmpeg -y -hwaccel cuda -i input_video -c:v h264_nvenc -preset fast -b:v bitrate -c:a copy output_video\n"

            "Nvidia cuvid\n"
            "ffmpeg -y -hwaccel cuvid -i input_video -c:v h264_nvenc -preset fast -b:v bitrate -c:a copy output_video\n"

            "Nvidia Cuda\n"
            "ffmpeg -y -hwaccel cuda -i input_video -c:v hevc_nvenc -preset fast -b:v bitrate -c:a copy output_video\n"

            "Nvidia cuvid\n"
            "ffmpeg -y -hwaccel cuvid -i input_video -c:v hevc_nvenc -preset fast -b:v bitrate -c:a copy output_video\n"
        )

        # Create a QMessageBox and set the style sheet to customize the font color
        about_box = QMessageBox(self)
        about_box.setWindowTitle("About Bulk Video Encoder")
        about_box.setText(about_text)

        # Show the "About" dialog
        about_box.exec_()

    def on_bitrate_mode_change(self, index):
        # Disable bitrate_combobox if "CBR" is selected
        is_cbr_selected = self.bitrate_mode_combobox.currentText() == "CBR"
        self.min_bitrate_combobox.setDisabled(is_cbr_selected)
        self.max_bitrate_combobox.setDisabled(is_cbr_selected)

        is_vbr_or_pvbr_selected = self.bitrate_mode_combobox.currentText() in ("VBR", "PVBR")
        self.bitrate_combobox.setDisabled(is_vbr_or_pvbr_selected)

    def select_input_files(self):
        file_names, _ = QFileDialog.getOpenFileNames(self, "Select Files", self.input_folder, "Video Files (*.mp4;*.mkv;*.avi;*.mov;*.wmv;*.flv;*.webm;*.mpeg;*.mpg;*.m4v;*.ts)")
        if file_names:
            self.input_folder = os.path.dirname(file_names[0])
            self.settings.setValue("input_folder", self.input_folder)
            current_row_count = self.table_widget.rowCount()
            new_row_count = current_row_count + len(file_names)
            self.table_widget.setRowCount(new_row_count)

            for i, file_name in enumerate(file_names, start=current_row_count):
                item = QTableWidgetItem(file_name)
                self.table_widget.setItem(i, 0, item)
                elapsed_time_item = QTableWidgetItem("--:--:--")
                self.table_widget.setItem(i, 1, elapsed_time_item)
                fps_item = QTableWidgetItem("--")
                self.table_widget.setItem(i, 2, fps_item)

            self.table_widget.resizeColumnsToContents()
            # Calculate the total width needed for all columns
            total_width = self.table_widget.verticalHeader().width()
            total_width += self.table_widget.horizontalScrollBar().height()
            for i in range(self.table_widget.columnCount()):
                total_width += self.table_widget.columnWidth(i)
                

    def select_output_folder(self):
        folder_name = QFileDialog.getExistingDirectory(self, "Select Folder", self.output_folder)
        if folder_name:
            self.output_textbox.setText(folder_name)
            self.output_folder = folder_name
            self.settings.setValue("output_folder", self.output_folder)

    def get_file_size(file_path):
        size_bytes = os.path.getsize(file_path)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024:
                return f"{size_bytes:.2f}{unit}"
            size_bytes /= 1024
        return f"{size_bytes:.2f}TB"

    def encode_videos(self,row):
        self.frame_count = 0
        input_files = []
        self.elapsed_time = 0
        self.elapsed_timer = QtCore.QTimer(self)
        self.elapsed_timer.timeout.connect(self.update_elapsed_time)
        self.elapsed_timer.start(1000)
        #self.status_label.setText("Encoding")
        # Store current settings in QSettings
        self.settings.setValue("bitrate", self.bitrate_combobox.currentText())
        self.settings.setValue("bitrate_mode", self.bitrate_mode_combobox.currentText())
        self.settings.setValue("min_bitrate", self.min_bitrate_combobox.currentText())
        self.settings.setValue("max_bitrate", self.max_bitrate_combobox.currentText())

        self.settings.setValue("preset", self.preset_combobox.currentText())
        self.settings.setValue("simultaneous_encodes", self.Simultaneous_Encodes_combobox.currentText())
        self.settings.setValue("hwaccel_index", self.hwaccel_combobox.currentIndex())
        self.settings.setValue("output_folder", self.output_textbox.text())

        self.table_widget.setItem(row, 4, QTableWidgetItem(""))


        for row in range(self.table_widget.rowCount()):
            input_files.append(self.table_widget.item(row, 0).text())

        output_folder = self.output_textbox.text()
        preset = self.preset_combobox.currentText()
        bitrate = self.bitrate_combobox.currentText()
        self.simultaneous_encodes = int(self.Simultaneous_Encodes_combobox.currentText())
        self.bitrate_mode_combobox
        self.min_bitrate_combobox.currentText()
        self.max_bitrate_combobox.currentText()
        selected_format = self.format_combobox.currentText()


        self.input_button.setEnabled(False)
        self.output_button.setEnabled(False)
        self.output_textbox.setEnabled(False)
        self.preset_combobox.setEnabled(False)
        self.bitrate_combobox.setEnabled(False)      
        self.hwaccel_combobox.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.Simultaneous_Encodes_combobox.setEnabled(False)
        self.encode_button.setEnabled(False)
        self.fps_queue.clear()
        self.frame_count_queue.clear()
        self.encoding_thread = VideoEncoderThread(input_files, output_folder, preset, bitrate, self.simultaneous_encodes, self.hwaccel_combobox.currentIndex(), self.bitrate_mode_combobox, self.min_bitrate_combobox, self.max_bitrate_combobox, self.format_combobox)
        self.encoding_thread.fps_updated.connect(self.update_fps_for_row)  # Connect to update_fps_for_row
        self.encoding_thread.encoding_canceled.connect(self.encoding_canceled_handler)
        self.cancel_button.clicked.connect(self.cancel_encoding_thread)
        self.encoding_thread.encoding_complete.connect(self.encoding_complete)  # Connect the signal to the slot
        self.encoding_thread.encoding_progress_updated.connect(self.update_encoding_progress)
        self.encoding_thread.encoding_completed.connect(self.encoding_completed_handler)
        self.encoding_thread.console_output_updated.connect(self.update_console_output)
        self.encoding_thread.start()
        self.start_time = time.time()

    def update_encoding_progress(self, row, status):
        self.table_widget.setItem(row, 4, QTableWidgetItem(status))
        
    def update_elapsed_time(self):
        self.elapsed_time += 1
        self.timer.start(500)
        hours = self.elapsed_time // 3600
        minutes = (self.elapsed_time % 3600) // 60
        seconds = self.elapsed_time % 60
        
        # update elapsed time in table
        for row in range(self.table_widget.rowCount()):
            if self.encoding_thread.started_encoding[row] and not self.encoding_thread.finished_encoding[row]:
          
                item = self.table_widget.item(row, 1)
                elapsed_time = item.data(QtCore.Qt.UserRole)
                if elapsed_time is None:
                    elapsed_time = 0
                elapsed_time += 1
                item.setText(f"{elapsed_time // 3600:02d}:{(elapsed_time % 3600) // 60:02d}:{elapsed_time % 60:02d}")
                item.setData(QtCore.Qt.UserRole, elapsed_time)
            
    @QtCore.pyqtSlot(int, float)  # Updated slot signature to accept both int and float
    def update_frame_and_fps_for_row(self, row, value):
        # Use the 'value' parameter to determine whether it's FPS or frame count update
        if isinstance(value, int):
            # Update the frame count for the corresponding row in the table widget
            item = self.table_widget.item(row, 1)
            item.setText(str(value))
        elif isinstance(value, float):
            # Update the FPS for the corresponding row in the table widget
            item = self.table_widget.item(row, 2)
            item.setText(str(value))

    @QtCore.pyqtSlot(int, float)
    def update_fps_for_row(self, row, fps):
        # Update the FPS for the corresponding row in the table widget
        fps_item = self.table_widget.item(row, 2)
        if fps_item is None:
            return  # Exit the method if the item does not exist

        fps_item.setText(f"{fps:.2f}")  # Keep FPS in float for more precision

        # Calculate remaining time
        total_frames = self.get_total_frames(row)
        
        # Access the processed_frames from the encoding_thread instance
        processed_frames = self.encoding_thread.get_processed_frames(row)  

        if total_frames and fps != 0:  # Make sure fps is not zero before performing the division
            remaining_frames = total_frames - processed_frames
            remaining_time = remaining_frames / fps

            # Update the remaining time in the table widget
            time_item = self.table_widget.item(row, 3)
            if time_item is None:
                time_item = QTableWidgetItem()
                self.table_widget.setItem(row, 3, time_item)

            # Format and set the remaining time
            hours, minutes, seconds = int(remaining_time // 3600), int((remaining_time % 3600) // 60), int(remaining_time % 60)
            time_item.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        self.table_widget.resizeColumnsToContents()


    def get_total_frames(self, row):
        # Get the total number of frames in the video using FFprobe
        input_file = self.table_widget.item(row, 0).text()
        duration = get_video_duration(input_file)
        if duration is not None:
            fps = self.current_fps
            return int(duration * fps)
        return None

    def cancel_encoding_thread(self,row):
        if hasattr(self, "encoding_thread") and self.encoding_thread.isRunning():
            self.encoding_thread.cancel_encoding()
            self.encoding_thread.terminate()  # Terminate the thread immediately without waiting
            self.elapsed_timer.stop()
            self.input_button.setEnabled(True)
            self.output_button.setEnabled(True)
            self.output_textbox.setEnabled(True)
            self.preset_combobox.setEnabled(True)
            self.bitrate_combobox.setEnabled(True)      
            self.Simultaneous_Encodes_combobox.setEnabled(True)
            self.encode_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.reset_ui()
            #self.status_label.setText("Encoding canceled")
            for row in range(self.table_widget.rowCount()):
                self.table_widget.setItem(row, 1, QTableWidgetItem("--:--:--"))  # Reset elapsed time (assuming it's column 1)
                self.table_widget.setItem(row, 3, QTableWidgetItem("--:--:--"))  # Reset time remaining (assuming it's column 3)

    @QtCore.pyqtSlot(int)
    def encoding_completed_handler(self, row):
        # Update column 5 for the corresponding row to "Done" when an encoding is completed
        self.table_widget.setItem(row, 4, QTableWidgetItem("Done"))
        self.encoding_thread.finished_encoding[row] = True
        self.reset_ui()

    @QtCore.pyqtSlot()
    def encoding_canceled_handler(self):
        self.cancel_button.setEnabled(False)
        self.encode_button.setEnabled(True)

        #self.status_label.setText("Encoding canceled")
        self.reset_ui()

    def encoding_complete(self):
        self.elapsed_timer.stop()
        self.timer.stop()
        self.input_button.setEnabled(True)
        self.output_button.setEnabled(True)
        self.output_textbox.setEnabled(True)
        self.preset_combobox.setEnabled(True)
        self.bitrate_combobox.setEnabled(True)
        self.Simultaneous_Encodes_combobox.setEnabled(True)
        self.encode_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.reset_ui()
        
        # Cleanup the encoding thread
        if hasattr(self, "encoding_thread") and self.encoding_thread.isRunning():
            self.encoding_thread.wait()  # Wait for the encoding thread to finish

    def closeEvent(self, event):
        # Check if the encoding thread is running and cancel it
        if hasattr(self, "encoding_thread") and self.encoding_thread.isRunning():
            self.encoding_thread.cancel_encoding()
            self.encoding_thread.wait()  # Wait for the encoding thread to finish

        # Call the default close event to allow the application to exit
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoEncoder()
    window.show()
    sys.exit(app.exec_())
