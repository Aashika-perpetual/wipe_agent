#!/bin/bash
set -e

echo "[INFO] Installing PC Wipe Agent..."

# -------------------------
# 1. Install dependencies
# -------------------------
sudo apt update
sudo apt install -y python3 python3-pip

pip3 install flask psutil

# -------------------------
# 2. Download agent script
# -------------------------
AGENT_DIR="/opt/pc_wipe_agent"

sudo mkdir -p $AGENT_DIR
sudo wget -O $AGENT_DIR/pc_wipe_agent.py \
  https://raw.githubusercontent.com/Aashika-perpetual/wipe_agent/main/pc_wipe_agent.py

sudo chmod +x $AGENT_DIR/pc_wipe_agent.py

# -------------------------
# 3. Create systemd service
# -------------------------
SERVICE_FILE=/etc/systemd/system/pc_wipe_agent.service

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=PC Wipe Agent Service
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/pc_wipe_agent/pc_wipe_agent.py
WorkingDirectory=/opt/pc_wipe_agent
Restart=always
User=root

[Install]
WantedBy=multi-user.target
EOF

# -------------------------
# 4. Reload + enable service
# -------------------------
sudo systemctl daemon-reload
sudo systemctl enable pc_wipe_agent.service
sudo systemctl start pc_wipe_agent.service

echo "[INFO] Installation complete."
echo "[INFO] Agent is running at: http://0.0.0.0:5055"
