import sys
import os
import time
import re
from datetime import datetime
import subprocess
from PyQt5 import QtCore
from PyQt5.QtCore import QThread
from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog, QLabel, QTableWidget, QPushButton, QComboBox, QTableWidgetItem, QLabel, \
    QWidget, QGridLayout, QHBoxLayout, QVBoxLayout, QFormLayout, QLineEdit, QTabWidget,QSizePolicy,QPlainTextEdit,QGroupBox,QAction,QMessageBox
from PyQt5.QtCore import QSettings

bitrate_num = "1M", "2M", "3M","4M", "5M","6M", "10M", "12M", "14M","20M", "30M", "40M", "50M"
sel_preset = "slow", "medium", "fast"
num_encodes = "1", "2", "3","4","5"

nvidia_gpu_available = False
try:
    subprocess.check_output(["nvidia-smi"])
    nvidia_gpu_available = True
except (subprocess.CalledProcessError, FileNotFoundError):
    pass
def check_amd_gpu():
    try:
        result = subprocess.run(
            ['lspci', '-nnk', '-d', '1002:'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = result.stdout.decode('utf-8').strip()
        return len(output) > 0
    except FileNotFoundError:
        return False

intel_gpu_available = False
try:
    subprocess.check_output(["lspci", "-nnk", "-d", "8086:"])
    intel_gpu_available = True
except (subprocess.CalledProcessError, FileNotFoundError):
    pass

amd_gpu_available = check_amd_gpu()

hwaccel = "auto"
if nvidia_gpu_available:
    hwaccel = "cuvid"
elif amd_gpu_available:
    hwaccel = "amf"
elif intel_gpu_available:
    hwaccel = "qsv"

if nvidia_gpu_available:
    encoder = "h264_nvenc"
elif amd_gpu_available:
    encoder = "h264_amf"
elif intel_gpu_available:
    encoder = "h264_qsv"
else:
    encoder = "libx264"

def get_video_duration(video_file):
    """Get the duration of a video using FFprobe."""
    command = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_file]
    try:
        output = subprocess.check_output(command, universal_newlines=True)
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

    def __init__(self, input_files, output_folder, preset, bitrate, simultaneous_encodes, hwaccel_index):
        super().__init__()
        self.input_files = input_files
        self.output_folder = output_folder
        self.preset = preset
        self.bitrate = bitrate
        self.simultaneous_encodes = simultaneous_encodes
        self.processes = []
        self.elapsed_times = [0] * len(input_files)
        self.start_times = [0] * len(input_files)
        self._is_canceled = False
        self.hwaccel_index = hwaccel_index  # Store the hwaccel_index as an instance variable
        # Add a list to keep track of videos that have started encoding
        self.started_encoding = [False] * len(input_files)
        
        

    def run(self):
        with ThreadPoolExecutor(max_workers=self.simultaneous_encodes) as executor:
            futures = []

            for i, input_file in enumerate(self.input_files):
                output_file = os.path.join(self.output_folder, os.path.basename(input_file))


                # Get the selected hardware acceleration option based on the index
                hwaccel_options = ["Nvidia_Cuda", "Nvidia_Cuvid", "AMD", "Intel"]
                if 0 <= self.hwaccel_index < len(hwaccel_options):
                    hwaccel = hwaccel_options[self.hwaccel_index]
                else:
                    hwaccel = "auto"

                if hwaccel  == "Nvidia_Cuvid":
                    command = [
                        "ffmpeg",
                        "-y",
                        "-hwaccel", "cuvid",
                        "-i", input_file,
                        "-c:v", "h264_nvenc",
                        "-preset", self.preset,
                        "-b:v", self.bitrate,
                        "-c:a", "copy",
                        output_file,
                    ]
                if hwaccel == "Nvidia_Cuda":
                    command = [
                        "ffmpeg",
                        "-y",
                        "-hwaccel", "cuda",
                        "-i", input_file,
                        "-c:v", "h264_nvenc",
                        "-preset", self.preset,
                        "-b:v", self.bitrate,
                        "-c:a", "copy",
                        output_file,
                    ]
                elif hwaccel  == "AMD":
                    command = [
                        "ffmpeg",
                        "-y",
                        "-hwaccel", "amf",
                        "-i", input_file,
                        "-c:v", "h264_amf",
                        "-preset", self.preset,
                        "-b:v", self.bitrate,
                        "-c:a", "copy",
                        output_file,
                    ]
                elif hwaccel  == "Intel":
                    command = [
                        "ffmpeg",
                        "-y",
                        "-hwaccel", "qsv",
                        "-i", input_file,
                        "-c:v", "h264_qsv",
                        "-preset", self.preset,
                        "-b:v", self.bitrate,
                        "-c:a", "copy",
                        output_file,
                    ]

                future = executor.submit(self.execute_ffmpeg, command, i)
                futures.append(future)


            for i, input_file in enumerate(self.input_files):
                self.encoding_progress_updated.emit(i, "Encoding")

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
        # Process the FFmpeg command and capture the output
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True)

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

        process.wait()

class VideoEncoder(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Video Encoder")
        self.setGeometry(100, 100, 1000, 800)
        self.setStyleSheet("""
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
        """)

        self.init_ui()

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
        self.table_widget.setColumnCount(5)  # Add one more column for "Encoding/Done"
        self.table_widget.setHorizontalHeaderLabels(["Input File", "Elapsed Time", "FPS", "Time Remaining", "Encoding/Done"])

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
        self.hwaccel_combobox = QComboBox(self.tab1)
        self.hwaccel_combobox.addItems(["Nvidia_Cuda", "Nvidia_Cuvid", "AMD", "Intel"])

        grid_layout.addWidget(QLabel("Simultaneous Encodes:"), 0, 0)
        grid_layout.addWidget(self.Simultaneous_Encodes_combobox, 0, 1)

        grid_layout.addWidget(QLabel("Bitrate:"), 0, 2)
        grid_layout.addWidget(self.bitrate_combobox, 0, 3)

        grid_layout.addWidget(QLabel("Preset:"), 1, 0)
        grid_layout.addWidget(self.preset_combobox, 1, 1)

        grid_layout.addWidget(QLabel("Hardware Acceleration:"), 1, 2)
        grid_layout.addWidget(self.hwaccel_combobox, 1, 3)

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

        self.bitrate_combobox.addItems(bitrate_num)
        self.preset_combobox.addItems(sel_preset)
        self.Simultaneous_Encodes_combobox.addItems(num_encodes)

        # Read previous settings using QSettings
        self.settings = QSettings("MyCompany", "VideoEncoder")
        previous_bitrate = self.settings.value("bitrate", "1M")
        previous_preset = self.settings.value("preset", "medium")
        previous_simultaneous_encodes = self.settings.value("simultaneous_encodes", "1")
        previous_hwaccel_index = int(self.settings.value("hwaccel_index", "0"))
        previous_output_folder = self.settings.value("output_folder", "")

        # Create and set default values for comboboxes
        self.bitrate_combobox.setCurrentText(previous_bitrate)
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
            about_text = """
            
            Simple Video Encoder/Converter for Nvidia, AMD, Intel GPUs
            Tested on Nvidia 3060, 3070, 4090

            Note: This application is a work in progress, and not all functions may work correctly.

            Version: 1.0

            Key Features:
            - GUI Interface for easy interaction
            - Hardware Acceleration for faster encoding (Cuvid, Cuda, AMF, QSV)
            - Concurrent Video Encoding for improved efficiency
            - Live Encoding Progress display with elapsed time, FPS, and time remaining
            - Customizable encoding settings (bitrate, preset)

            ffmpeg commands are:

            Nvidia Cuda
            ffmpeg -y -hwaccel cuda -i input_video -c:v h264_nvenc -preset"fast" -b:v bitrate -c:a copy output_video
            Nvidia cuvid
            ffmpeg -y -hwaccel cuvid -i input_video -c:v h264_nvenc -preset"fast" -b:v bitrate -c:a copy output_video
            AMD
            ffmpeg -y -hwaccel amf -i input_video -c:v h264_nvenc -preset"fast" -b:v bitrate -c:a copy output_video
            Intel
            ffmpeg -y -hwaccel qsv -i input_video -c:v h264_nvenc -preset"fast" -b:v bitrate -c:a copy output_video

            """
            # Create a QMessageBox and set the style sheet to customize the font color
            about_box = QMessageBox(self)
            about_box.setWindowTitle("About Bulk Video Encoder")
            about_box.setText(about_text)
            about_box.setStyleSheet("""
                QLabel {
                    color: black;
                    font-size: 14px;
                }
            """)

            # Show the "About" dialog
            about_box.exec_()

    def select_input_files(self):
        
        file_names, _ = QFileDialog.getOpenFileNames(self, "Select Files", self.input_folder, "Video Files (*.mp4;*.mkv;*.avi;*.mov;*.wmv;*.flv;*.webm;*.mpeg;*.mpg;*.m4v;*.ts)")
        if file_names:
            self.input_folder = os.path.dirname(file_names[0])
            self.settings.setValue("input_folder", self.input_folder)
            self.table_widget.setRowCount(len(file_names))
            for i, file_name in enumerate(file_names):
                item = QTableWidgetItem(file_name)
                self.table_widget.setItem(i, 0, item)
                elapsed_time_item = QTableWidgetItem("--:--:--")
                self.table_widget.setItem(i, 1, elapsed_time_item)
                fps_item = QTableWidgetItem("--")
                self.table_widget.setItem(i, 2, fps_item)
            self.table_widget.resizeColumnsToContents()

    def select_output_folder(self):
        
        folder_name = QFileDialog.getExistingDirectory(self, "Select Folder", self.output_folder)
        if folder_name:
            self.output_textbox.setText(folder_name)
            self.output_folder = folder_name
            self.settings.setValue("output_folder", self.output_folder)

    def encode_videos(self):
        self.frame_count = 0
        input_files = []
        self.elapsed_time = 0
        self.elapsed_timer = QtCore.QTimer(self)
        self.elapsed_timer.timeout.connect(self.update_elapsed_time)
        self.elapsed_timer.start(1000)
        #self.status_label.setText("Encoding")
        # Store current settings in QSettings
        self.settings.setValue("bitrate", self.bitrate_combobox.currentText())
        self.settings.setValue("preset", self.preset_combobox.currentText())
        self.settings.setValue("simultaneous_encodes", self.Simultaneous_Encodes_combobox.currentText())
        self.settings.setValue("hwaccel_index", self.hwaccel_combobox.currentIndex())
        self.settings.setValue("output_folder", self.output_textbox.text())

        for row in range(self.table_widget.rowCount()):
            input_files.append(self.table_widget.item(row, 0).text())

        output_folder = self.output_textbox.text()
        preset = self.preset_combobox.currentText()
        bitrate = self.bitrate_combobox.currentText()
        self.simultaneous_encodes = int(self.Simultaneous_Encodes_combobox.currentText())

        self.input_button.setEnabled(False)
        self.output_button.setEnabled(False)
        self.output_textbox.setEnabled(False)
        self.preset_combobox.setEnabled(False)
        self.bitrate_combobox.setEnabled(False)      
        self.cancel_button.setEnabled(True)
  
        self.Simultaneous_Encodes_combobox.setEnabled(False)
        self.encode_button.setEnabled(False)
        self.fps_queue.clear()
        self.frame_count_queue.clear()

        self.encoding_thread = VideoEncoderThread(input_files, output_folder, preset, bitrate, self.simultaneous_encodes, self.hwaccel_combobox.currentIndex())
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
            if self.encoding_thread.started_encoding[row]:  # Check if encoding has started for the item
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
        item = self.table_widget.item(row, 2)
        if item is None:
            return  # Exit the method if the item does not exist

        item.setText(str(int(fps)))  # Convert FPS to integer and update the table widget

        # Calculate time remaining
        total_frames = self.get_total_frames(row)
        if total_frames and fps != 0:  # Make sure fps is not zero before performing the division
            elapsed_time = self.table_widget.item(row, 1).data(QtCore.Qt.UserRole)
            if elapsed_time:
                elapsed_time = int(elapsed_time)
                time_remaining = (total_frames - self.frame_count) / fps

                # Make sure the item exists before setting the text
                item = self.table_widget.item(row, 3)
                if item is None:
                    item = QTableWidgetItem()
                    self.table_widget.setItem(row, 3, item)

                # Convert time_remaining to int before formatting the string
                time_remaining_int = int(time_remaining)
                item.setText(f"{time_remaining_int // 3600:02d}:{(time_remaining_int % 3600) // 60:02d}:{time_remaining_int % 60:02d}")

    def get_total_frames(self, row):
        # Get the total number of frames in the video using FFprobe
        input_file = self.table_widget.item(row, 0).text()
        duration = get_video_duration(input_file)
        if duration is not None:
            fps = self.current_fps
            return int(duration * fps)
        return None

    def cancel_encoding_thread(self):
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
            #self.status_label.setText("Encoding canceled")

    @QtCore.pyqtSlot(int)
    def encoding_completed_handler(self, row):
        # Update column 5 for the corresponding row to "Done" when an encoding is completed
        self.table_widget.setItem(row, 4, QTableWidgetItem("Done"))
        
    @QtCore.pyqtSlot()
    def encoding_canceled_handler(self):
        self.cancel_button.setEnabled(False)
        self.encode_button.setEnabled(True)
        #self.status_label.setText("Encoding canceled")

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
