from http.server import BaseHTTPRequestHandler, HTTPServer
import json

class MockOllama(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/api/generate':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            response = {
                "model": "llama3.2",
                "response": "### ?? Safari Trip Plan: Simulated Local Itinerary\n\nThis is a mocked response from the local AI simulator testing the integration."
            }
            self.wfile.write(json.dumps(response).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass # Suppress logging

server = HTTPServer(('localhost', 11434), MockOllama)
print("Mock Ollama server listening on port 11434...")
server.serve_forever()
