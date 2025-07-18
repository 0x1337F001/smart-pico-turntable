
# Smart Pico Turntable

This repository contains the MicroPython firmware for a 3D-printable, web-controlled smart turntable. It is designed to run on a Raspberry Pi Pico W and is perfect for photogrammetry, 3D scanning, 360° product photography, and creating smooth video shots.

The turntable can be controlled via a responsive web interface that works on both desktop and mobile devices.

![Smart-Pico-Turntable](/assets/images/1.jpg) ![Smart-Pico-Turntable](/assets/images/3.jpg)
## Features

- **Responsive Web Interface:** Control the turntable from any device with a web browser.
- **Continuous Spin Mode:** Rotate the turntable at three configurable speeds (Slow, Normal, Fast).
- **Photo Sequence Mode:** Automate the process of taking photos at precise angular intervals (e.g., every 10 degrees).
- **Canon DSLR Trigger:** Wired via a 2.5mm jack or IR (Infrared), emulating Canon RC-6 remote.
- **Configurable Hardware:** Settings allow you to specify whether your build includes the IR transmitter.
- **Persistent Settings:** All settings are saved to a `config.json` file on the Pico, so your configuration is remembered after a reboot.
- **Physical Button Control:** A single button allows for cycling through speeds and toggling the start/stop.

## Setup

 1. **Hardware:** Assemble the 3D printed turntable and wire the components according to the project guide on [MakerWorld](https://makerworld.com/en/models/1579183).
 2. **Flash MicroPython:** Flash the latest version of MicroPython for the Raspberry Pi Pico W to your device.
3. **Upload Files:** Copy the files from this repository to the root directory of your Pico's filesystem.
4. **First Boot:** The device will create a config.json file with default settings on its first run.
5. **Connect & Configure:**
   - The turntable will attempt to connect to the Wi-Fi networks defined in `config.json`.
   - If it cannot connect, it will start its own Access Point (AP). Connect to this AP (default SSID is `SmartTurntableAP`, default password is `your_strong_password`).
   - Navigate to the device's IP address in a web browser and go to the "Settings" page to configure your Wi-Fi credentials, hardware version, and other preferences.
   - Alternatively you can configure your Wi-Fi credentials by editing the `config.json`.
## Dependencies

This project relies on the following excellent open-source libraries.

- [miguelgrinberg/microdot](https://github.com/miguelgrinberg/microdot): A lightweight and efficient web server for MicroPython.
- [peterhinch/micropython_ir](https://github.com/peterhinch/micropython_ir): Used for sending IR camera shutter commands. You only need the ir_tx directory.
- [larsks/micropython-stepper-motor](https://github.com/larsks/micropython-stepper-motor): The stepper motor library used for controlling the turntable.


## License

[MIT](https://choosealicense.com/licenses/mit/)

