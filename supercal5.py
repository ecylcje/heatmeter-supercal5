#!/usr/bin/env python3
import time
import json
import serial
import struct
import configparser
import os
import paho.mqtt.client as mqtt

CONFIG_FILE = "supercal5.conf"

# ---------------------------------------------------------
# Load configuration
# ---------------------------------------------------------
def load_config():
    cfg = configparser.ConfigParser()

    if not os.path.exists(CONFIG_FILE):
        print(f"Config file {CONFIG_FILE} not found. Using defaults.")
        return {
            "mqtt_host": "localhost",
            "mqtt_port": 1883,
            "mqtt_user": "",
            "mqtt_pass": "",
            "serial_port": "/dev/ttyAMA0",
            "baud_rate": 2400,
            "meter_addr": 1,
            "poll_interval": 300,
        }

    cfg.read(CONFIG_FILE)

    return {
        "mqtt_host": cfg.get("MQTT", "host", fallback="localhost"),
        "mqtt_port": cfg.getint("MQTT", "port", fallback=1883),
        "mqtt_user": cfg.get("MQTT", "username", fallback=""),
        "mqtt_pass": cfg.get("MQTT", "password", fallback=""),

        "serial_port": cfg.get("MBUS", "serial_port", fallback="/dev/ttyAMA0"),
        "baud_rate": cfg.getint("MBUS", "baud_rate", fallback=2400),
        "meter_addr": cfg.getint("MBUS", "meter_address", fallback=1),
        "poll_interval": cfg.getint("MBUS", "poll_interval", fallback=300),
    }

cfg = load_config()

MQTT_HOST = cfg["mqtt_host"]
MQTT_PORT = cfg["mqtt_port"]
MQTT_USER = cfg["mqtt_user"]
MQTT_PASS = cfg["mqtt_pass"]

SERIAL_PORT = cfg["serial_port"]
BAUD_RATE = cfg["baud_rate"]
METER_ADDR = cfg["meter_addr"]
POLL_INTERVAL = cfg["poll_interval"]

# ---------------------------------------------------------
# Constants
# ---------------------------------------------------------
DISCOVERY_PREFIX = "homeassistant"
STATE_TOPIC = "supercal5/state"
DEVICE_ID = "supercal5_meter"

HEAT_CONSTANT = 4150.0  # matches EmonHub

# VIF scaling table
VIF_SCALE = {
    0x03: (0.001, "kWh"),
    0x04: (0.01,  "kWh"),
    0x05: (0.1,   "kWh"),
    0x06: (1.0,   "kWh"),
    0x13: (0.001, "m³"),
    0x14: (0.01,  "m³"),
    0x15: (0.1,   "m³"),
    0x16: (1.0,   "m³"),
    0x2A: (0.1,   "W"),
    0x2B: (1.0,   "W"),
    0x2C: (10.0,  "W"),
    0x2D: (100.0, "W"),
    0x2E: (1000.0,"W"),
    0x3B: (0.001, "m³/h"),
    0x3C: (0.01,  "m³/h"),
    0x3D: (0.1,   "m³/h"),
    0x3E: (1.0,   "m³/h"),
    0x59: (0.01,  "°C"),
    0x5A: (0.1,   "°C"),
    0x5B: (1.0,   "°C"),
    0x5D: (0.01,  "°C"),
    0x5E: (0.1,   "°C"),
    0x5F: (1.0,   "°C"),
}

# DIF length table
DIF_LENGTH = {
    0x0: 0,
    0x1: 1,
    0x2: 2,
    0x3: 3,
    0x4: 4,
    0x5: 4,
    0x6: 6,
    0x7: 8,
}

# Sensors to publish
SENSORS = {
    "energy":      (0x03, "Energy",       "kWh",  "energy",      "total_increasing"),
    "volume":      (0x13, "Volume",       "m³",   "water",       "total_increasing"),
    "power":       (0x2B, "Power",        "W",    "power",       "measurement"),
    "temp_flow":   (0x5B, "Flow Temp",    "°C",   "temperature", "measurement"),
    "temp_return": (0x5F, "Return Temp",  "°C",   "temperature", "measurement"),
    "flow_rate":   (0x3E, "Flow Rate",    "m³/h", None,          "measurement"),
}

# ---------------------------------------------------------
# Main class
# ---------------------------------------------------------
class Supercal5Bridge:
    def __init__(self):
        self.ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=2)

        self.client = mqtt.Client()
        if MQTT_USER:
            self.client.username_pw_set(MQTT_USER, MQTT_PASS)
        self.client.connect(MQTT_HOST, MQTT_PORT)
        self.client.loop_start()

        time.sleep(1)
        self.send_discovery()

    # ---------------- Low-level M-Bus ----------------

    def _checksum(self, data):
        return sum(data) & 0xFF

    def _send_short_frame(self, control, addr):
        cs = (control + addr) & 0xFF
        frame = bytes([0x10, control, addr, cs, 0x16])
        self.ser.write(frame)

    def _read_long_frame(self, timeout=2.0):
        start = time.time()
        buf = []

        while time.time() - start < timeout:
            b = self.ser.read(1)
            if not b:
                continue
            val = b[0]
            buf.append(val)

            if len(buf) == 1 and buf[0] != 0x68:
                buf = []
                continue

            if len(buf) == 4 and buf[0] == 0x68:
                length = buf[1]
                if buf[2] != length or buf[3] != 0x68:
                    buf = []
                    continue

            if len(buf) >= 4:
                length = buf[1]
                total_len = length + 6
                if len(buf) == total_len:
                    cs_calc = self._checksum(buf[4:-2])
                    if cs_calc != buf[-2] or buf[-1] != 0x16:
                        return None
                    return buf
        return None

    # ---------------- Decoding ----------------

    def decode_bcd(self, data):
        val = 0
        for byte in reversed(data):
            hi = (byte >> 4) & 0xF
            lo = byte & 0xF
            if hi > 9 or lo > 9:
                return None
            val = val * 10 + hi
            val = val * 10 + lo
        return val

    def parse_frame_values(self, frame):
        if not frame or len(frame) < 10:
            return []

        length = frame[1]
        data_start = 7
        data_end = 4 + length - 1
        i = data_start
        results = []

        while i < data_end:
            dif = frame[i]
            i += 1

            if dif == 0x2F:
                continue

            data_len = DIF_LENGTH.get(dif & 0x0F, 0)
            if i >= data_end:
                break

            vif = frame[i]
            i += 1

            while vif & 0x80 and i < data_end:
                vif = frame[i]
                i += 1

            if data_len == 0 or i + data_len > data_end:
                i += data_len
                continue

            raw = frame[i:i+data_len]
            i += data_len

            raw_val = self.decode_bcd(raw)
            if raw_val is None:
                continue

            scale, _ = VIF_SCALE.get(vif, (1.0, None))
            value = raw_val * scale
            results.append((vif, value))

        return results

    def read_all_values(self):
        self._send_short_frame(0x40, METER_ADDR)
        time.sleep(0.2)

        values = []

        self._send_short_frame(0x7B, METER_ADDR)
        f1 = self._read_long_frame()
        if f1:
            values.extend(self.parse_frame_values(f1))

        self._send_short_frame(0x5B, METER_ADDR)
        f2 = self._read_long_frame()
        if f2:
            values.extend(self.parse_frame_values(f2))

        return values

    # ---------------- Home Assistant Discovery ----------------

    def send_discovery(self):
        print("Sending Home Assistant discovery configs...")

        for key, (vif, name, unit, dev_class, state_class) in SENSORS.items():
            topic = f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}_{key}/config"
            payload = {
                "name": f"Supercal 5 {name}",
                "stat_t": STATE_TOPIC,
                "val_tpl": "{{ value_json." + key + " }}",
                "uniq_id": f"{DEVICE_ID}_{key}",
                "dev": {
                    "ids": [DEVICE_ID],
                    "name": "Supercal 5",
                    "mf": "Sontex",
                },
            }
            if unit:
                payload["unit_of_meas"] = unit
            if dev_class:
                payload["dev_cla"] = dev_class
            if state_class:
                payload["stat_cla"] = state_class

            self.client.publish(topic, json.dumps(payload), retain=True)

        heat_topic = f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}_heat_output/config"
        heat_payload = {
            "name": "Supercal 5 Heat Output",
            "stat_t": STATE_TOPIC,
            "val_tpl": "{{ value_json.heat_W }}",
            "unit_of_meas": "W",
            "dev_cla": "power",
            "stat_cla": "measurement",
            "uniq_id": f"{DEVICE_ID}_heat_output",
            "dev": {
                "ids": [DEVICE_ID],
                "name": "Supercal 5",
                "mf": "Sontex",
            },
        }
        self.client.publish(heat_topic, json.dumps(heat_payload), retain=True)

    # ---------------- Main Loop ----------------

    def run(self):
        print(f"Polling meter every {POLL_INTERVAL}s...")

        while True:
            try:
                values = self.read_all_values()
                if not values:
                    print("No valid data from meter.")
                    time.sleep(POLL_INTERVAL)
                    continue

                vif_map = {vif: val for vif, val in values}
                result = {}

                for key, (vif, _, _, _, _) in SENSORS.items():
                    if vif in vif_map:
                        result[key] = vif_map[vif]

                if (
                    "flow_rate" in result and
                    "temp_flow" in result and
                    "temp_return" in result
                ):
                    flow_m3h = result["flow_rate"]
                    dT = result["temp_flow"] - result["temp_return"]
                    flow_m3s = flow_m3h / 3600.0
                    heat_W = HEAT_CONSTANT * dT * flow_m3s
                    result["heat_W"] = heat_W

                if result:
                    self.client.publish(STATE_TOPIC, json.dumps(result))
                    print(f"Published: {result}")
                else:
                    print("No mapped values found.")

            except Exception as e:
                print(f"Error: {e}")

            time.sleep(POLL_INTERVAL)

# ---------------------------------------------------------
# Run
# ---------------------------------------------------------
if __name__ == "__main__":
    bridge = Supercal5Bridge()
    bridge.run()
