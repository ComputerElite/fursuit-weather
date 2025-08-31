#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import time
import json
from prometheus_client import start_http_server, Gauge, REGISTRY
from prometheus_client.core import GaugeMetricFamily

TEMPERATURE_GAUGE = Gauge('suit_temperature_celsius', 'Room temperature in Celsius')
HUMIDITY_GAUGE = Gauge('suit_humidity_percent', 'Room humidity in percent')
PRESSURE_GAUGE = Gauge('suit_pressure_hpa', 'Room pressure in hPa')
ALTITUDE_GAUGE = Gauge('suit_altitude_meters', 'Room altitude in meters')
STEPS_COUNTER = Gauge('suit_steps_taken', 'Steps taken')
IMU_WORKING_GAUGE = Gauge("suit_imu_working", "1 if IMU is working, 0 if not")
last_message_time = 0  # Unix timestamp of last POST
last_down = time.time()
steps = 0
STEPS_FILE = "/app/data/steps.txt"

# Load steps from file if it exists
if os.path.exists(STEPS_FILE):
    with open(STEPS_FILE, "r") as f:
        try:
            steps = int(f.read().strip())
        except ValueError:
            print("Invalid step count in steps.txt, resetting to 0.")
            steps = 0
print(f"Loaded steps: {steps}")

STEPS_COUNTER.set(steps)

class ESP32Collector:
    def collect(self):
        global last_down
        now = time.time()
        age = now - last_message_time

        gauge = GaugeMetricFamily("suit_last_message_age", "Time since last message")
        gauge.add_metric([], age)
        yield gauge

        status = 1 if age < 10 else 0  # 1 = up, 0 = down
        gauge2 = GaugeMetricFamily("suit_up", "1 if up, 0 if down")
        gauge2.add_metric([], status)
        yield gauge2
        
        if status == 0:
            last_down = time.time()
        
        up_since = now - last_down
        gauge3 = GaugeMetricFamily("suit_up_since_seconds", "seconds since the suit has been considered up")
        gauge3.add_metric([], up_since if up_since > 10 else 0)
        yield gauge3

REGISTRY.register(ESP32Collector())

SAVE_DIR = "./uploads"  # Updated directory

upload_password = ""
if "DATA_SERVER_PASSWORD" in os.environ:
    upload_password = os.environ["DATA_SERVER_PASSWORD"]
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        global last_message_time
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        supplied_password = self.headers.get("Authentication")
        if supplied_password == None or not upload_password in supplied_password:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Unauthenticated.\n")
            return
        try:
            # Try to parse as JSON
            parsed = json.loads(body)
        except json.JSONDecodeError as e:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"Invalid JSON: {e}\n".encode())
            return
        
        self.send_response(200)
        self.end_headers()
        if "t" in parsed and parsed["t"] < 180:
            TEMPERATURE_GAUGE.set(parsed["t"])
        if "h" in parsed:
            HUMIDITY_GAUGE.set(parsed["h"])
        if "p" in parsed and parsed["p"] > 0:
            PRESSURE_GAUGE.set(parsed["p"])
        if "a" in parsed and parsed["a"] < 4000:
            ALTITUDE_GAUGE.set(parsed["a"])
        if "imu_working" in parsed:
            IMU_WORKING_GAUGE.set(1 if parsed["imu_working"] else 0)
        if "steps" in parsed:
            global steps
            steps += parsed["steps"]
            STEPS_COUNTER.set(steps)
            with open(STEPS_FILE, "w") as f:
                f.write(str(steps))

        last_message_time = time.time()

        self.wfile.write(b"Valid JSON received and saved.\n")

if __name__ == "__main__":
    server_address = ('', 9999)  # Updated port
    httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)
    print(f"Starting server on port {server_address[1]}...")
    start_http_server(9998)
    print("Prometheus metrics available at http://localhost:9999/metrics")
    httpd.serve_forever()
