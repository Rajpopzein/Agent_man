import os
from googleapiclient.discovery import build
from google.oauth2 import service_account
from mcp.server.fastmcp import FastMCP

# Initialize MCP server
mcp = FastMCP("GoogleDriveServer")

def get_service():
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
    creds = service_account.Credentials.from_service_account_file(creds_path)
    return build('drive', 'v3', credentials=creds)

@mcp.tool()
def list_files(page_size: int = 10):
    """List files from Google Drive"""
    service = get_service()
    results = service.files().list(pageSize=page_size, fields='files(id, name)').execute()
    return results.get('files', [])

if __name__ == "__main__":
    mcp.run()
