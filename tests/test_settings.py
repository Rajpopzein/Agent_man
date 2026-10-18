import unittest

class TestSettings(unittest.TestCase):
    def test_settings_file_exists(self):
        with open('docs/settings.md', 'r') as file:
            content = file.read()
            self.assertIn('Google Drive MCP Server', content)

if __name__ == '__main__':
    unittest.main()