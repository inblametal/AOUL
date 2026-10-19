# 🦾 AOUL: AI Robotics Copilot & Autonomous Systems Optimizer

<p align="center">
  <strong>Actuator • Orientation • Undefined-behavior • Locator</strong><br>
  <em>The Zero-Dependency, 100% Offline AI Pair Programmer for ROS 2 & Autonomous Robotics</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Platform-macOS%20%7C%20Windows%20%7C%20Linux-blue?style=flat-square" alt="Platform" />
  <img src="https://img.shields.io/badge/Python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-success?style=flat-square" alt="Python Version" />
  <img src="https://img.shields.io/badge/ROS%202-Humble%20%7C%20Iron%20%7C%20Jazzy-orange?style=flat-square" alt="ROS 2 Support" />
  <img src="https://img.shields.io/badge/Local%20LLM-Qwen%202.5%20Coder-purple?style=flat-square" alt="Qwen Coder" />
  <img src="https://img.shields.io/badge/Air--Gapped-100%25%20Offline-emerald?style=flat-square" alt="Offline Ready" />
</p>

---

## 🧭 The 4 Pillars of AOUL

* **A — Actuator**: Motor drivers, velocity/effort drives, CAN/EtherCAT bus timing, hardware torque limits, and emergency-stop (`cmd_vel` zero-velocity) shutdown guarantees.
* **O — Orientation**: 3D spatial kinematics, quaternions, Euler angle conversions, TF2 tree extrapolation errors, and IMU sensor fusion.
* **U — Undefined-behavior**: Multi-threaded executor deadlocks, race conditions in `ReentrantCallbackGroup`, unhandled sensor `NaN`/`Inf` math exceptions, and DDS QoS mismatches.
* **L — Locator**: SLAM, Nav2 costmaps, wheel odometry drift, EKF state estimation, and sensor watchdog failovers.

---

## ✨ Features at a Glance

* **100% Offline & Air-Gapped Ready**: All frontend assets (Tailwind CSS, Lucide icons, native macOS/Windows system fonts) and the AI engine (local **Qwen Coder** via Ollama) run strictly on local loopback (`127.0.0.1`).
* **Real-Time Token Streaming**: Server-Sent Events (SSE) with instant sub-millisecond heartbeats eliminate socket drops and render responses live as the model formulates code.
* **Interactive Thinking Animations**: Visual popping waves, glowing avatar radar pulses, and active status rotators keep you informed while the AI processes kinematics and code logic.
* **6 Built-in Themes**:
  * ⚡ **Cyber Cyan** (Default deep midnight & neon cyan)
  * ⚠️ **Industrial Amber** (KUKA / Fanuc / Warehouse safety gold)
  * 📟 **Matrix Emerald** (High-contrast hacker terminal green)
  * 🌌 **Cosmic Indigo** (JPL / NASA rover aerospace violet)
  * 🔴 **Crimson Hazard** (Safety-critical high-alert crimson)
  * ☀️ **Clean Lab** (Bright laboratory daylight mode)
* **Static Robotics Safety Fuzzer**: Detects runaway robot hazards, missing E-stops, and unhandled NaN sensor streams with AST inspection.
* **ROS 2 QoS RxO Validator**: Mathematically validates compatibility between Publishers and Subscribers (Reliability, Durability, History depth).
* **TF2 Tree Diagnostics**: Automatically diagnoses extrapolation into the future/past and frame jump anomalies.

---

## 📦 Downloads & Installation

### 🍎 macOS (`AOUL.dmg` / Native Cocoa App)
1. Download **`dist/AOUL.dmg`** from releases or the `dist/` folder.
2. Open the DMG and drag **`AOUL.app`** into your **`Applications`** folder.
3. Double-click **AOUL** in `/Applications` or launch via Spotlight (`Cmd + Space`).
4. *Or build from source:*
   ```bash
   bash scripts/build_dmg.sh
   ```

### 🪟 Windows (`AOUL.exe` / 1-Click Batch)
1. Download **`dist/AOUL.exe`** or **`run_windows.bat`**.
2. Double-click **`AOUL.exe`** to launch the standalone desktop app.
3. On Windows, AOUL automatically opens in a dedicated frameless app window using Microsoft Edge / Chrome.
4. *Or build Windows executable from source:*
   ```bash
   python3 scripts/build_windows_exe.py
   ```

### 🐧 Linux / Development Workspace
```bash
# Clone the repository
git clone https://github.com/your-username/AOUL.git
cd AOUL

# Launch the desktop web workspace
python3 run.py
```

---

## 🧠 Local Qwen Coder Setup (24/7 Offline AI)

AOUL automatically discovers local models running through [Ollama](https://ollama.com/):

```bash
# 1. Install Ollama (macOS, Windows, or Linux)
# https://ollama.com/download

# 2. Pull Qwen 2.5 Coder (State-of-the-art coding model)
ollama pull qwen2.5-coder

# 3. For ultra-fast CPU inference on laptops:
ollama pull qwen2.5:0.5b
```

AOUL pins the model weights in unified memory with a 24-hour keep-alive for instant inference.

---

## 💻 CLI Tools

AOUL also ships with a command-line interface:

```bash
# Audit a ROS 2 node for safety loopholes
python3 run.py --cli audit my_robot_node.py

# Triage runtime crash logs
python3 run.py --cli triage /path/to/ros2_crash.log

# Check DDS Quality of Service (QoS) compatibility
python3 run.py --cli check-qos --pub-rel BEST_EFFORT --sub-rel RELIABLE

# Scaffold a hardened differential drive node
python3 run.py --cli generate diff_drive --output safe_drive.py
```

---

## 🛠 Project Structure

```
AOUL/
├── AOUL.app/               # Native macOS Universal Mach-O bundle (x86_64 + arm64)
├── dist/                   # Distributable platform installers
│   ├── AOUL.dmg            # macOS Drag-and-Drop Disk Image installer
│   ├── AOUL.exe            # Windows Standalone 64-bit PE Executable
│   └── run_windows.bat     # Windows 1-click launch script
├── robosage/               # Core Python Engine
│   ├── agent/              # Multi-turn reasoning, prompts & tool orchestrator
│   ├── diagnostics/        # Loophole fuzzer, QoS checker & TF2 analyzer
│   ├── llm/                # Qwen Coder, Ollama & offline heuristic providers
│   ├── templates/          # Production ROS 2 node code generators
│   └── web/                # Local UI dashboard, offline vendor libraries & themes
├── scripts/
│   ├── build_app.sh        # Compiles native macOS Cocoa universal app
│   ├── build_dmg.sh        # Builds compressed macOS .dmg installer
│   └── build_windows_exe.py# Packages standalone Windows .exe
├── src_macos/main.m        # Native Objective-C Cocoa/WebKit wrapper
├── run.py                  # Cross-platform application entry point
├── run_windows.bat         # Portable Windows launcher
├── pyproject.toml          # Project configuration & metadata
└── requirements.txt        # Zero external pip dependencies required
```

---

## 🧪 Testing

Run the comprehensive unit test suite:

```bash
python3 -m unittest discover tests
```

---

## 📜 License

Apache-2.0 © 2026 AOUL Autonomous Systems.
