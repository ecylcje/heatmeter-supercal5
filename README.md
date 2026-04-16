# Supercal 5 M‑Bus → MQTT Bridge  
A lightweight Python bridge for reading **Sontex Supercal 5** heat meters over **M‑Bus** and publishing decoded values to **MQTT**, including **Home Assistant auto‑discovery** and **calculated heat output (W)**.

This project is designed for:

- Air‑source heat pump monitoring  
- Heat‑meter telemetry  
- Home Assistant integrations  
- Long‑interval, battery‑safe polling  
- Direct M‑Bus wired connections (e.g., /dev/ttyAMA0 or USB‑M-Bus adapters)

It implements the **correct Supercal 5 M‑Bus protocol**, including:

- SND_NKE (normalize)  
- Multi‑frame REQ_UD2 (7B + 5B)  
- DIF/VIF decoding  
- BCD decoding  
- Checksum validation  
- Heat calculation using flow rate + ΔT  

---

## Features

### ✔ Correct Supercal 5 M‑Bus protocol  
Reads both frames of REQ_UD2 and decodes all DIF/VIF records.

### ✔ MQTT publishing  
Publishes all decoded values as a single JSON payload.

### ✔ Home Assistant auto‑discovery  
Automatically creates sensors for:

- Energy  
- Volume  
- Power  
- Flow temperature  
- Return temperature  
- Flow rate  
- **Heat output (W)**  

### ✔ Config‑file support  
No credentials or settings inside the script.

### ✔ Battery‑safe  
Default polling interval is 300 seconds (5 minutes).

---

## Requirements

- Python 3.8+
- A wired M‑Bus interface (e.g., USB‑M-Bus level converter)
- A running MQTT broker
- A Sontex Supercal 5 heat meter

Python dependencies:

pip install paho-mqtt pyserial

---

## Installation

Clone the repository:

git clone https://github.com/ecylcje/heatmeter-supercal5.git

cd heatmeter-supercal5


Install dependencies:

pip install -r paho-mqtt
pip install -r pyserial

(Or install manually: `paho-mqtt` and `pyserial`.)

---

## Configuration

All settings are stored in **supercal5.conf**.

Create or edit:

supercal5.conf


Example:

[MQTT]

host = mqtt.demo.example

port = 1883

username = mqtt

password = mqtt_password


[MBUS]

serial_port = /dev/ttyAMA0

baud_rate = 2400

meter_address = 1

poll_interval = 300



### MQTT Settings

| Key | Description |
|-----|-------------|
| host | MQTT broker hostname |
| port | MQTT port (usually 1883) |
| username | MQTT username |
| password | MQTT password |

### M‑Bus Settings

| Key | Description |
|-----|-------------|
| serial_port | M‑Bus serial device (e.g., /dev/ttyAMA0, /dev/ttyUSB0) |
| baud_rate | Usually 2400 for Supercal 5 |
| meter_address | Primary M‑Bus address (default 1) |
| poll_interval | Seconds between polls |

---

## Running the Script

Run directly:

python3 supercal5.py

You should see output like:

Sending Home Assistant discovery configs...

Polling meter every 300s...

Published: {'energy': 54999, 'temp_flow': 50.14, 'temp_return': 50.13, 'flow_rate': 0.23, 'heat_W': 1234.5}


---

## Home Assistant Integration

Because the script publishes **MQTT auto‑discovery**, Home Assistant will automatically detect the device.

Navigate to:

**Settings → Devices & Services → MQTT → Supercal 5**

You will see sensors for:

- Energy (kWh)  
- Volume (m³)  
- Power (W)  
- Flow temperature (°C)  
- Return temperature (°C)  
- Flow rate (m³/h)  
- **Heat output (W)**  

No YAML required.

---

## Systemd Service (optional)

If you want the script to run automatically on boot, create:

/etc/systemd/system/supercal5.service

[Unit]
Description=Supercal 5 M-Bus Reader
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/supercal5.py
WorkingDirectory=/path/to/
Restart=always

[Install]
WantedBy=multi-user.target

Enable:

sudo systemctl enable supercal5
sudo systemctl start supercal5


---

## Troubleshooting

### No response from meter  
Check:

- Wiring polarity (M‑Bus is polarity‑insensitive, but some adapters aren’t)
- Correct primary address
- Correct baud rate (Supercal 5 default = 2400)
- Serial permissions (`sudo usermod -a -G dialout <user>`)

### Home Assistant sensors not appearing  
Check:

- MQTT discovery enabled in HA  
- MQTT credentials correct  
- Discovery prefix is `homeassistant`  

---

## License

MIT License — free to use, modify, and share.



