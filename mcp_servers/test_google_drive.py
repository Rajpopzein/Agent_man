import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from google_drive import GoogleDriveServer

def test_connection():
    server = GoogleDriveServer('credentials.json')
    server.connect()
    files = server.list_files()
    assert files == []
    print('Test passed!')

if __name__ == '__main__':
    test_connection()