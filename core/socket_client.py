import os
from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication

class SocketClient(QObject):
    """
    Handles communication with Scan.exe via a QLocalSocket on Windows.
    Listens for 'sonAppExit' to cleanly shutdown the application.
    Can send messages to trigger Scan.exe UI updates (e.g., 'tuyuan*...', 'realimage*...').
    """
    def __init__(self, server_name="ShortMsgSocket", parent=None):
        super().__init__(parent)
        self.client = QLocalSocket(self)
        self.server_name = server_name
        self._connected = False

        self.client.connected.connect(self._on_connected)
        self.client.readyRead.connect(self._on_ready_read)
        self.client.errorOccurred.connect(self._on_error)

    def connect_to_server(self):
        """Attempts to connect to the local socket server created by Scan.exe"""
        # QDir::tempPath() + "/ShortMsgSocket" is used in Scan/ptview
        import tempfile
        socket_path = os.path.join(tempfile.gettempdir(), self.server_name)
        # On Windows QLocalSocket uses named pipes, QDir::tempPath() handling might differ slightly
        # in Qt C++ vs Python but generally Qt abstracts this. We use the exact name Qt expects.
        self.client.connectToServer(socket_path)
        print(f"SocketClient: Attempting connection to {socket_path}")

    def send_message(self, msg: str):
        """Sends a string message to Scan.exe if connected"""
        if self._connected:
            self.client.write(msg.encode('utf-8'))
            self.client.flush()
            print(f"SocketClient: Sent -> {msg}")
        else:
            print(f"SocketClient: Not connected, cannot send -> {msg}")

    def _on_connected(self):
        self._connected = True
        print("SocketClient: Connected to Scan.exe server successfully.")

    def _on_ready_read(self):
        data = self.client.readAll()
        reply = bytes(data).decode('utf-8').strip()
        print(f"SocketClient: Received <- {reply}")
        
        if reply == "sonAppExit":
            print("SocketClient: Received sonAppExit command, tearing down.")
            QApplication.quit()

    def _on_error(self, socket_error):
        print(f"SocketClient: Connection Error: {self.client.errorString()}")
        self._connected = False
