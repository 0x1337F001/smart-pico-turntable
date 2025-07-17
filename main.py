# main.py - Final Version with Settings, Debugging, and Separate HTML
import uasyncio
import network
import ujson
from machine import Pin, reset
from microdot import Microdot, Response, send_file
from microdot.websocket import with_websocket
from ir_tx.rp2_rmt import RP2_RMT
from array import array
import motor # Changed from 'stepper'
import gc
import utime

# --- Hardware Setup (Pins are now constants) ---
STEPPER_PINS = [21, 20, 19, 18]
BUTTON_PIN_NUM = 22
WIRED_SHUTTER_PIN_NUM = 10
IR_TX_PIN_NUM = 13
STEPS_PER_DEGREE = (1650688 * 6) / (360 * 810)
CONFIG_FILE = 'config.json'
HTML_FILE = 'index.html'
SETTINGS_HTML_FILE = 'settings.html'

# --- Global State & Settings ---
lock = uasyncio.Lock()
clients = set()
settings = {}
op_mode = 'IDLE'
op_params = {}
status_message = "Ready"
SPIN_SPEEDS = []
current_speed_index = 1
button_press_start_time = 0
is_button_down = False
long_press_action_taken = False
button_action_pending = None
button_state = 'IDLE'
debounce_deadline = 0
trigger_mode = 'WIRED'

# --- Settings and Configuration Management ---
def load_settings():
    """Loads settings from config.json, or creates it with defaults."""
    global SPIN_SPEEDS, trigger_mode
    try:
        with open(CONFIG_FILE, 'r') as f:
            s = ujson.load(f)
            print("Settings loaded from config.json")
    except (OSError, ValueError):
        print("Config file not found or invalid. Creating with default settings.")
        s = {
            "hostname": "smart-turntable",
            "hardware": {"version": "with_ir"},
            "wifi_networks": [
                {"ssid": "YourPrimarySSID", "password": "YourPrimaryPassword"},
                {"ssid": "YourSecondarySSID", "password": "YourSecondaryPassword"}
            ],
            "ap_settings": {
                "ssid": "SmartTurntableAP",
                "password": "your_strong_password"
            },
            "speeds_ms": {"slow": 13, "normal": 4, "fast": 1},
            "photo_delays_ms": {"short": 500, "medium": 1000, "long": 2000},
            "startup": {"autospin": True},
        }
        save_settings(s) # Save the defaults
    
    SPIN_SPEEDS = [s['speeds_ms']['slow'], s['speeds_ms']['normal'], s['speeds_ms']['fast']]
    
    return s

def save_settings(new_settings):
    """Saves the provided dictionary to config.json."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            ujson.dump(new_settings, f)
        print("Settings saved successfully.")
        return True
    except OSError as e:
        print(f"Error saving settings: {e}")
        return False

# --- Initialize Hardware & Load Settings ---
settings = load_settings()
onboard_led = Pin('LED', Pin.OUT, value=0)
stepper_motor = motor.FullStepMotor.frompins(*STEPPER_PINS) # Changed from 'stepper'
wired_shutter = Pin(WIRED_SHUTTER_PIN_NUM, Pin.OUT, value=0)
ir_transmitter = RP2_RMT(pin_pulse=None, carrier=(Pin(IR_TX_PIN_NUM, Pin.OUT), 32700, 33))
SHUTTER_SIGNAL = array('H', [550, 7200, 550, 40000, 0])
button = Pin(BUTTON_PIN_NUM, Pin.IN, Pin.PULL_DOWN)

# --- Initialize Microdot App ---
app = Microdot()

# --- Helper Functions ---
async def connect_to_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.config(hostname=settings.get('hostname', 'pico-turntable'))
    for net in settings.get('wifi_networks', []):
        if wlan.isconnected(): return True
        print(f"Connecting to {net['ssid']}...")
        wlan.connect(net['ssid'], net['password'])
        for _ in range(10):
            if wlan.isconnected():
                print(f"Connected! IP: {wlan.ifconfig()[0]}")
                onboard_led.off()
                return True
            onboard_led.toggle()
            await uasyncio.sleep_ms(1000)
    print("Failed to connect to any saved Wi-Fi networks.")
    onboard_led.off()
    return False

def start_access_point():
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap_ssid = settings.get('ap_settings', {}).get('ssid', 'PicoTurntableAP')
    ap_password = settings.get('ap_settings', {}).get('password', 'your_strong_password')
    ap.config(essid=ap_ssid, password=ap_password, hostname=settings.get('hostname', 'pico-turntable'))
    print(f"Access Point '{ap_ssid}' started! IP: {ap.ifconfig()[0]}")
    onboard_led.on()

def get_web_page(file_path):
    try:
        return send_file(file_path)
    except OSError:
        return "<h1>Error</h1><p>Could not load web interface. Make sure {} is on the device.</p>".format(file_path), 500

async def pulse_motor(repetitions=1):
    print(f"DIAGNOSTIC: Pulsing motor {repetitions} time(s).")
    stepper_motor.stepms = 2
    for _ in range(repetitions):
        for _ in range(25):
            stepper_motor.step(1)
            await uasyncio.sleep_ms(2)
        for _ in range(25):
            stepper_motor.step(-1)
            await uasyncio.sleep_ms(2)
        await uasyncio.sleep_ms(50)
    for pin in stepper_motor.pins: pin.value(0)

# --- WebSocket and Broadcast Logic ---
async def broadcast_status():
    global status_message, op_mode, op_params, current_speed_index, SPIN_SPEEDS, trigger_mode
    async with lock:
        current_speed = op_params.get('speed', SPIN_SPEEDS[current_speed_index])
        payload = {
            "message": status_message, 
            "mode": op_mode, 
            "speed": current_speed,
            "trigger_mode": trigger_mode,
        }
        json_payload = ujson.dumps(payload)
    for client in list(clients):
        try:
            await client.send(json_payload)
        except Exception:
            clients.remove(client)

# --- Camera Trigger Function ---
async def trigger_camera():
    global trigger_mode
    onboard_led.on()

    if trigger_mode == 'WIRED':
        wired_shutter.on()
        await uasyncio.sleep_ms(200)
        wired_shutter.off()
    elif trigger_mode == 'IR':
        ir_transmitter.send(SHUTTER_SIGNAL)
            
    await uasyncio.sleep_ms(50)
    onboard_led.off()

# --- Command Handler ---
async def handle_command(data):
    global op_mode, op_params, current_speed_index, trigger_mode, SPIN_SPEEDS
    command = data.get('command')
    
    if command == 'set_trigger_mode':
        async with lock:
            new_mode = data.get('mode')
            if new_mode in ['WIRED', 'IR']: trigger_mode = new_mode
    elif command == 'start_spin':
        async with lock:
            speed = data.get('speed', settings['speeds_ms']['normal'])
            if speed in SPIN_SPEEDS: current_speed_index = SPIN_SPEEDS.index(speed)
            op_mode, op_params = 'SPIN', {'speed': speed}
    elif command == 'set_speed':
        async with lock:
            if op_mode == 'SPIN':
                speed = data.get('speed', settings['speeds_ms']['normal'])
                op_params['speed'] = speed
                if speed in SPIN_SPEEDS: current_speed_index = SPIN_SPEEDS.index(speed)
    elif command == 'start_photo_sequence':
        async with lock:
            deg = data.get('deg', 45)
            speed = data.get('speed', settings['speeds_ms']['normal'])
            delay = data.get('delay', settings['photo_delays_ms']['medium'])
            op_mode, op_params = 'SEQUENCE', {'deg': deg, 'speed': speed, 'delay': delay}
    elif command == 'take_picture':
        async with lock: op_mode = 'PICTURE'
    elif command == 'stop':
        async with lock: op_mode = 'IDLE'
    elif command == 'debug_ir_trigger':
        print("DEBUG: Triggering IR")
        ir_transmitter.send(SHUTTER_SIGNAL)
    elif command == 'debug_wired_shutter':
        state = data.get('state', False)
        print(f"DEBUG: Setting Wired Shutter to {'ON' if state else 'OFF'}")
        wired_shutter.value(1 if state else 0)

# --- Microdot Route Handlers ---
@app.route('/')
async def index(request):
    return get_web_page(HTML_FILE)

@app.route('/settings')
async def settings_page(request):
    return get_web_page(SETTINGS_HTML_FILE)

@app.route('/api/settings', methods=['GET', 'POST'])
async def api_settings(request):
    global settings
    if request.method == 'POST':
        try:
            new_settings = request.json
            if save_settings(new_settings):
                settings = new_settings
                return Response(body={'status': 'ok', 'message': 'Settings saved. Rebooting to apply all changes...'}, status_code=200)
            else:
                return Response(body={'status': 'error', 'message': 'Failed to save settings to file.'}, status_code=500)
        except Exception as e:
            return Response(body={'status': 'error', 'message': f'Invalid data format: {e}'}, status_code=400)
    else: # GET
        return Response(body=settings, headers={'Content-Type': 'application/json'})

@app.route('/api/reboot', methods=['POST'])
async def api_reboot(request):
    print("Reboot requested from web interface.")
    await uasyncio.sleep_ms(1000)
    reset()
    return Response(body={'status': 'ok', 'message': 'Rebooting...'})


@app.route('/ws')
@with_websocket
async def websocket_handler(request, ws):
    print("Client connected to WebSocket.")
    clients.add(ws)
    try:
        await broadcast_status()
        while True:
            message = await ws.receive()
            try:
                data = ujson.loads(message)
                await handle_command(data)
                await broadcast_status()
            except ValueError:
                print(f"Received invalid JSON: {message}")

    except Exception as e:
        print(f"WebSocket Error/Disconnect: {e}")
    finally:
        clients.remove(ws)
        print("Client disconnected.")

# --- Interrupt handler ---
def button_handler(pin):
    global button_press_start_time, is_button_down, long_press_action_taken, button_action_pending, button_state, debounce_deadline
    if button_state == 'DEBOUNCING': return
    if pin.value() == 1:
        if not is_button_down:
            is_button_down, long_press_action_taken = True, False
            button_press_start_time = utime.ticks_ms()
    else:
        if is_button_down:
            is_button_down = False
            if not long_press_action_taken:
                button_action_pending = 'cycle_speed'
                button_state, debounce_deadline = 'DEBOUNCING', utime.ticks_add(utime.ticks_ms(), 250)

# --- Motor Control Task ---
async def motor_control_task():
    global op_mode, op_params, status_message, button_action_pending, current_speed_index, is_button_down, long_press_action_taken, button_state, debounce_deadline, SPIN_SPEEDS
    last_op_mode, applied_spin_speed = 'NONE', -1
    seq_step, seq_total_steps, seq_steps_per_rotation, seq_steps_to_rotate_remaining = 0, 0, 0, 0
    sub_state = 'DONE'
    last_broadcast_time = 0

    while True:
        if button_state == 'DEBOUNCING' and utime.ticks_diff(utime.ticks_ms(), debounce_deadline) > 0:
            button_state = 'IDLE'
        if is_button_down and not long_press_action_taken:
            if utime.ticks_diff(utime.ticks_ms(), button_press_start_time) >= 500:
                long_press_action_taken, button_action_pending = True, 'toggle_spin'
                button_state, debounce_deadline = 'DEBOUNCING', utime.ticks_add(utime.ticks_ms(), 250)
        if button_action_pending is not None:
            action, button_action_pending = button_action_pending, None
            async with lock:
                if action == 'cycle_speed':
                    current_speed_index = (current_speed_index + 1) % len(SPIN_SPEEDS)
                elif action == 'toggle_spin':
                    if op_mode == 'SPIN': op_mode = 'IDLE'
                    else: op_mode, op_params['speed'] = 'SPIN', SPIN_SPEEDS[current_speed_index]

        try:
            async with lock:
                current_mode = op_mode
                desired_spin_speed = SPIN_SPEEDS[current_speed_index]
            if current_mode != last_op_mode:
                sub_state = 'DONE'
                applied_spin_speed = -1
                for pin in stepper_motor.pins: pin.value(0)
            last_op_mode = current_mode
            old_status = status_message
            
            if current_mode == 'IDLE':
                status_message = "Ready"
                for pin in stepper_motor.pins: pin.value(0)
                await uasyncio.sleep_ms(100)
            elif current_mode == 'SPIN':
                if applied_spin_speed != desired_spin_speed:
                    applied_spin_speed = desired_spin_speed
                    stepper_motor.stepms = applied_spin_speed
                    async with lock:
                        op_params['speed'] = applied_spin_speed
                        status_message = f"Spinning (speed: {applied_spin_speed}ms/step)"
                stepper_motor.step(1)
                await uasyncio.sleep_ms(0)
            elif current_mode == 'PICTURE':
                status_message = "Taking picture..."
                await trigger_camera()
                async with lock: op_mode, status_message = 'IDLE', "Picture complete. Ready."
            elif current_mode == 'SEQUENCE':
                if sub_state == 'DONE':
                    async with lock:
                        deg = op_params.get('deg', 45)
                        speed = op_params.get('speed', settings['speeds_ms']['normal'])
                        delay = op_params.get('delay', settings['photo_delays_ms']['medium'])
                    stepper_motor.stepms = speed
                    seq_total_steps = 360 // deg if deg > 0 else 4
                    seq_steps_per_rotation = int(deg * STEPS_PER_DEGREE)
                    seq_steps_to_rotate_remaining = seq_steps_per_rotation
                    seq_step = 0
                    sub_state = 'TRIGGER'
                if sub_state == 'TRIGGER':
                    status_message = f"Sequence {seq_step + 1}/{seq_total_steps}: Processing..."
                    await trigger_camera()
                    async with lock: delay_ms = op_params.get('delay', settings['photo_delays_ms']['medium'])
                    await uasyncio.sleep_ms(delay_ms)
                    if seq_step >= seq_total_steps - 1:
                        status_message, sub_state = "Sequence complete. Ready.", 'DONE'
                        async with lock: op_mode = 'IDLE'
                    else:
                        sub_state = 'ROTATE'
                elif sub_state == 'ROTATE':
                    status_message = f"Sequence {seq_step + 1}/{seq_total_steps}: Rotating..."
                    current_rotation_steps = seq_steps_to_rotate_remaining
                    for _ in range(current_rotation_steps):
                        async with lock:
                            if op_mode != 'SEQUENCE': break
                        stepper_motor.step(1)
                        await uasyncio.sleep_ms(0)
                    if op_mode == 'SEQUENCE':
                        seq_step += 1
                        seq_steps_to_rotate_remaining = seq_steps_per_rotation
                        sub_state = 'TRIGGER'
            
            if status_message != old_status: await broadcast_status(); last_broadcast_time = utime.ticks_ms()
            if current_mode == 'IDLE' and utime.ticks_diff(utime.ticks_ms(), last_broadcast_time) > 5000:
                await broadcast_status(); gc.collect(); last_broadcast_time = utime.ticks_ms()
        except Exception as e:
            print(f"FATAL ERROR in motor task: {e}")
            async with lock: status_message, op_mode = f"Error: {e}", 'IDLE'

# --- Main Asynchronous Execution Function ---
async def main():
    global op_mode, op_params
    
    # --- Set initial operating mode ---
    async with lock:
        if settings.get('startup', {}).get('autospin', True):
            op_mode = 'SPIN'
            op_params['speed'] = SPIN_SPEEDS[current_speed_index]
            print("DIAGNOSTIC: Autospin enabled. Setting initial state to SPIN.")
    
    # --- Connect to network ---
    if not await connect_to_wifi():
        start_access_point()
    
    # --- Give haptic feedback ---
    await pulse_motor(repetitions=2)
    
    # --- Start background tasks ---
    button.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=button_handler)
    motor_task = uasyncio.create_task(motor_control_task())
    server_task = uasyncio.create_task(app.start_server(port=80, debug=False))
    
    print("DIAGNOSTIC: Gathering and running tasks...")
    await uasyncio.gather(motor_task, server_task)

# --- Main Execution Block ---
if __name__ == '__main__':
    try:
        uasyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted")
    finally:
        uasyncio.new_event_loop()
