# Copy this file to config.py and fill in your values.
# config.py is gitignored and should never be committed.

GEMINI_API_KEY = ""

# Lutron Caséta
# Run 'python lutron.py pair <BRIDGE_IP>' to generate certificates in certs/
LUTRON_BRIDGE_IP = ""  # e.g. "192.168.2.50"
LUTRON_KEY_PATH = "certs/caseta.key"
LUTRON_CERT_PATH = "certs/caseta.crt"
LUTRON_CA_PATH = "certs/caseta-bridge.crt"

# Optional: IDs of Lutron lights to flash for announcements (leave empty to disable)
# e.g. ["2", "5"]
LUTRON_DINNER_BELL_ZONES = []
LUTRON_SHABBAT_REMINDER_ZONES = []

