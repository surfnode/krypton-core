# Krypton Core

A high-performance, open-source GGUF model manager and Hugging Face discovery engine designed for local AI workflows on Linux.

Built with Python and PyQt6, **Krypton Core** pairs seamlessly with `llama.cpp` (`llama-server`) to provide a minimal, native, and unbloated alternative to proprietary model hubs.

---

## Features

* **Discover & Download:** Query the Hugging Face Hub API for top GGUF repositories, inspect available quantization tiers, and stream downloads with live progress metrics.
* **Storage & Cache Manager:** Audit downloaded `.gguf` weights, track total disk consumption in `~/.cache/llama.cpp`, and remove unneeded quants with a single click.
* **Llama.cpp Native:** Automatically routes models to the standard cache directory scanned by `llama-server --models-dir`.
* **Zero Bloat:** Lightweight desktop footprint with no background telemetry or proprietary runtime locks.

---

## Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/surfnode/krypton-core.git](https://github.com/surfnode/krypton-core.git)
   cd krypton-core
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install PyQt6 requests
   ```

4. **Launch the manager:**
   ```bash
   python manager.py
   ```

---

## License

This project is licensed under the MIT License.
