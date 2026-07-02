@echo off
python -m nuitka --onefile --windows-console-mode=disable --include-data-files=resources/mohseni.ico=resources/mohseni.ico --enable-plugins=pyqt6 --windows-icon-from-ico=resources/mohseni.ico --output-dir=dist --remove-output MaxBridge_Assistant_v2.py
pause
