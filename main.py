import cv2
import numpy as np
from urllib.parse import urlparse, parse_qs, unquote
import threading
import winsound
import os
import random
import time
from playsound3 import playsound
from pyzbar.pyzbar import decode as zbar_decode

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ==========================================
# ASSET MAPPING (EXPLICIT SUBFOLDER RESOLVER)
# ==========================================

AUDIO_NAMES = {
    "UPI": ["audiogpay.mp3", "gpay.mp3"],
    "WIFI": ["audiowifi.mp3", "wifi.mp3"],
    "URL": ["audiourl.mp3", "url.mp3"],
    "DEFAULT": ["audiourl.mp3"]
}

MEME_NAMES = {
    "UPI": ["memegpay.jpg", "memegpay.png", "memegpay.jpeg", "gpay.jpg", "gpay.png"],
    "WIFI": ["memewifi.jpg", "memewifi.png", "memewifi.jpeg", "wifi.jpg", "wifi.png"],
    "URL": ["memeurl.jpg", "memeurl.png", "memeurl.jpeg", "url.jpg", "url.png"],
    "DEFAULT": ["memedefault.jpg", "memedefault.png", "default.jpg"]
}

def resolve_file_path(filename_list, subfolders=["audio", "meme", ""]):
    """Finds files across subfolders and returns absolute path with forward slashes."""
    for sub in subfolders:
        for fname in filename_list:
            if sub:
                target = os.path.join(BASE_DIR, sub, fname)
            else:
                target = os.path.join(BASE_DIR, fname)
            if os.path.isfile(target):
                return os.path.abspath(target).replace("\\", "/")
    return None

def play_retro_scan_sound():
    def _sound():
        for freq in [350, 500, 700, 950, 1200]:
            try:
                winsound.Beep(freq, 25)
            except Exception:
                pass
    threading.Thread(target=_sound, daemon=True).start()

def play_loading_click():
    def _click():
        try:
            winsound.Beep(1300, 15)
        except Exception:
            pass
    threading.Thread(target=_click, daemon=True).start()

def play_roast_clip_async(category):
    def _play():
        candidates = AUDIO_NAMES.get(category, AUDIO_NAMES["DEFAULT"])
        filepath = resolve_file_path(candidates, subfolders=["audio", ""])
        if filepath and os.path.exists(filepath):
            try:
                print(f"[AUDIO] Playing verified file: {filepath}")
                playsound(filepath)
            except Exception as e:
                print(f"[AUDIO ERROR] playsound failed: {e}")
        else:
            print(f"[AUDIO ERROR] No audio file found for category: {category}")
            
    threading.Thread(target=_play, daemon=True).start()


# ==========================================
# PURPOSE DETECTION ENGINE
# ==========================================

def detect_qr_purpose(qr_data):
    if not qr_data or not qr_data.strip():
        return "UNKNOWN PURPOSE", {}, "DEFAULT"

    raw = qr_data.strip()

    if raw.lower().startswith("upi://"):
        parsed = urlparse(raw)
        query = parse_qs(parsed.query)
        upi_id = query.get("pa", ["Unknown"])[0]
        name = unquote(query.get("pn", ["Merchant"])[0])
        amount = query.get("am", [""])[0]

        purpose = "SEND MONEY (UPI)"
        details = {"Recipient": name, "UPI ID": upi_id}
        if amount:
            details["Amount"] = f"INR {amount}"
        return purpose, details, "UPI"

    if "WIFI:" in raw.upper():
        ssid = "Unknown"
        security = "WPA/WPA2"
        wifi_str = raw[raw.upper().find("WIFI:") + 5:]
        parts = wifi_str.split(";")
        for part in parts:
            part = part.strip()
            if part.upper().startswith("S:"):
                ssid = part[2:]
            elif part.upper().startswith("T:"):
                security = part[2:]

        purpose = "CONNECT TO WIFI"
        details = {"Network": ssid, "Security": security}
        return purpose, details, "WIFI"

    if raw.lower().startswith("http://") or raw.lower().startswith("https://"):
        parsed = urlparse(raw)
        host = parsed.netloc if parsed.netloc else "Website"
        purpose = "OPEN WEBSITE"
        details = {
            "Host": host,
            "Path": parsed.path if len(parsed.path) < 28 else parsed.path[:25] + "..."
        }
        return purpose, details, "URL"

    preview = raw if len(raw) < 38 else raw[:35] + "..."
    return "DISPLAY TEXT", {"Content": preview}, "DEFAULT"


# ==========================================
# GRID TIMING TRACK DETECTION
# ==========================================

def detect_grid_size(binary):
    h, w = binary.shape
    candidate_sizes = [21 + (v - 1) * 4 for v in range(1, 15)]
    best_size = 21
    min_error = float("inf")

    for size in candidate_sizes:
        mod_w = w / size
        mod_h = h / size
        y_center = int(6.5 * mod_h)
        if y_center >= h:
            continue

        row_sample = binary[y_center, :]
        matches = 0
        total = 0

        for col in range(8, size - 8):
            x_center = int((col + 0.5) * mod_w)
            if x_center < w:
                expected = 0 if (col % 2 == 0) else 255
                if row_sample[x_center] == expected:
                    matches += 1
                total += 1

        if total > 0:
            error = 1.0 - (matches / total)
            if error < min_error:
                min_error = error
                best_size = size

    if min_error > 0.40:
        row_top = binary[int(h * 0.06), :]
        diffs = np.diff(row_top.astype(np.int32))
        transitions = np.where(diffs != 0)[0]
        if len(transitions) >= 2:
            finder_w = transitions[1] - transitions[0]
            est_module = max(1.0, finder_w / 7.0)
            est_size = int(round(w / est_module))
            best_size = min(candidate_sizes, key=lambda s: abs(s - est_size))

    return best_size

def order_points(pts):
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


# ==========================================
# METRICS ANALYSIS
# ==========================================

def analyze_qr(frame, polygon_pts, decoded_str):
    rect = order_points(polygon_pts)
    size = 500
    dst = np.array([
        [0, 0],
        [size - 1, 0],
        [size - 1, size - 1],
        [0, size - 1]
    ], dtype="float32")

    matrix = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(frame, matrix, (size, size))

    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    if np.mean(binary[0:15, 0:15]) < 50 and np.mean(binary[-15:, -15:]) < 50:
        binary = cv2.bitwise_not(binary)

    grid_size = detect_grid_size(binary)
    version = (grid_size - 21) // 4 + 1
    cell_size = size / grid_size

    black_squares = 0
    white_squares = 0

    for r in range(grid_size):
        for c in range(grid_size):
            y1 = int((r + 0.25) * cell_size)
            y2 = int((r + 0.75) * cell_size)
            x1 = int((c + 0.25) * cell_size)
            x2 = int((c + 0.75) * cell_size)

            cell = binary[y1:y2, x1:x2]
            avg = np.mean(cell) if cell.size > 0 else binary[int((r + 0.5) * cell_size), int((c + 0.5) * cell_size)]

            if avg < 128:
                black_squares += 1
            else:
                white_squares += 1

    total_modules = grid_size * grid_size
    black_pct = (black_squares / total_modules) * 100.0
    white_pct = (white_squares / total_modules) * 100.0
    dominant = "BLACK" if black_squares > white_squares else "WHITE"

    diff = abs(black_pct - white_pct)
    if diff < 5:
        personality = "BALANCED CHAOS"
    elif black_squares > white_squares:
        personality = "DARK AND MYSTERIOUS"
    else:
        personality = "BRIGHT AND OPTIMISTIC"

    purpose, purpose_details, audio_category = detect_qr_purpose(decoded_str)
    grid_visual = cv2.resize(binary, (260, 260), interpolation=cv2.INTER_NEAREST)

    return {
        "grid_size": grid_size,
        "version": version,
        "black_squares": black_squares,
        "white_squares": white_squares,
        "total_modules": total_modules,
        "black_percent": black_pct,
        "white_percent": white_pct,
        "dominant": dominant,
        "personality": personality,
        "purpose": purpose,
        "purpose_details": purpose_details,
        "audio_category": audio_category,
        "grid_visual": grid_visual
    }


# ==========================================
# DRAMATIC LOADING BUFFER
# ==========================================

def run_dramatic_loading_sequence(frame, window_name):
    stages = [
        (0.20, "SCANNING MODULE TIMING TRACKS..."),
        (0.45, "MEASURING MODULE COVERAGE & BLOCKS..."),
        (0.70, "CONSULTING CID MOOSA INTELLIGENCE..."),
        (0.90, "FINALIZING ABSOLUTE ZERO VALUE..."),
        (1.00, "USELESSNESS CONFIRMED (100%)")
    ]

    h, w = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, h), (10, 10, 10), -1)
    base_frame = cv2.addWeighted(overlay, 0.45, frame, 0.55, 0)

    bar_w = int(w * 0.7)
    bar_h = 28
    bar_x = (w - bar_w) // 2
    bar_y = h // 2

    for progress, msg in stages:
        t_start = time.time()
        play_loading_click()

        while time.time() - t_start < 0.35:
            display = base_frame.copy()

            cv2.rectangle(display, (bar_x - 30, bar_y - 80), (bar_x + bar_w + 30, bar_y + 80), (25, 25, 25), -1)
            cv2.rectangle(display, (bar_x - 30, bar_y - 80), (bar_x + bar_w + 30, bar_y + 80), (0, 255, 255), 2)

            cv2.putText(display, f"// {msg}", (bar_x - 10, bar_y - 35), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 255), 2)

            cv2.rectangle(display, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (50, 50, 50), -1)
            fill_w = int(bar_w * progress)
            cv2.rectangle(display, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), (0, 0, 255), -1)
            cv2.rectangle(display, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (200, 200, 200), 2)

            cv2.putText(display, f"{int(progress * 100)}%", (bar_x + bar_w + 10, bar_y + 20),
                        cv2.FONT_HERSHEY_DUPLEX, 0.6, (255, 255, 255), 1)

            cv2.imshow(window_name, display)
            if cv2.waitKey(20) & 0xFF == ord('q'):
                return


# ==========================================
# CERTIFICATE GENERATION
# ==========================================

def create_certificate(data):
    width = 1200
    height = 850
    cert = np.ones((height, width, 3), dtype=np.uint8) * 245

    # Decorative borders
    cv2.rectangle(cert, (20, 20), (width - 20, height - 20), (40, 40, 40), 4)
    cv2.rectangle(cert, (35, 35), (width - 35, height - 35), (100, 100, 100), 2)

    # Header
    cv2.putText(cert, "CERTIFICATE", (370, 95), cv2.FONT_HERSHEY_DUPLEX, 2.0, (30, 30, 30), 4)
    cv2.putText(cert, "OF QR ANALYSIS", (410, 145), cv2.FONT_HERSHEY_DUPLEX, 1.1, (50, 50, 50), 2)
    cv2.putText(cert, "THIS QR CODE HAS BEEN OFFICIALLY ANALYZED", (300, 195), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (50, 50, 50), 2)
    cv2.putText(cert, "AND FOUND TO BE...", (460, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (50, 50, 50), 2)
    cv2.putText(cert, "ABSOLUTELY USELESS!", (300, 295), cv2.FONT_HERSHEY_DUPLEX, 1.5, (0, 0, 180), 3)

    cv2.line(cert, (40, 320), (width - 40, 320), (180, 180, 180), 1)

    # QR Thumbnail
    qr_img = cv2.cvtColor(data["grid_visual"], cv2.COLOR_GRAY2BGR)
    cv2.rectangle(qr_img, (0, 0), (259, 259), (0, 0, 0), 2)
    cert[370:630, 60:320] = qr_img
    cv2.putText(cert, "ANALYZED QR CODE", (90, 675), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (40, 40, 40), 2)

    # Details
    start_x = 365
    start_y = 390
    ratio = round(data['black_squares'] / max(1, data['white_squares']), 2)
    details = [
        f"Grid Dimension:    {data['grid_size']} x {data['grid_size']} (Version {data['version']})",
        f"Total Block Count: {data['total_modules']} Blocks",
        f"Black Blocks:      {data['black_squares']} ({data['black_percent']:.1f}%)",
        f"White Blocks:      {data['white_squares']} ({data['white_percent']:.1f}%)",
        f"Dominant Colour:   {data['dominant']}",
        f"Block Density:     {ratio} Black/White Ratio"
    ]

    cv2.putText(cert, "ANALYSIS DETAILS", (start_x, 355), cv2.FONT_HERSHEY_DUPLEX, 0.75, (30, 30, 30), 2)
    for i, text in enumerate(details):
        cv2.putText(cert, text, (start_x, start_y + (i * 32)), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (40, 40, 40), 2)

    # Purpose Box
    cv2.rectangle(cert, (720, 350), (1140, 520), (80, 80, 80), 3)
    cv2.putText(cert, "QR PURPOSE", (840, 385), cv2.FONT_HERSHEY_DUPLEX, 0.75, (30, 30, 30), 2)
    cv2.putText(cert, data["purpose"], (735, 425), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 0, 180), 2)

    detail_y = 460
    for key, value in data["purpose_details"].items():
        text = f"{key}: {value}"
        if len(text) > 36:
            text = text[:33] + "..."
        cv2.putText(cert, text, (735, detail_y), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (40, 40, 40), 1)
        detail_y += 24

    # Personality Box
    cv2.rectangle(cert, (365, 590), (680, 700), (100, 100, 100), 2)
    cv2.putText(cert, "QR PERSONALITY", (405, 625), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (30, 30, 30), 2)
    cv2.putText(cert, data["personality"], (385, 665), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 180), 2)

    # Uselessness Stamp
    cv2.rectangle(cert, (365, 715), (680, 785), (0, 150, 200), 2)
    cv2.putText(cert, "USELESSNESS: 100%", (400, 760), cv2.FONT_HERSHEY_DUPLEX, 0.75, (0, 0, 180), 2)

    # Embed Meme Image
    meme_candidates = MEME_NAMES.get(data["audio_category"], MEME_NAMES["DEFAULT"])
    meme_path = resolve_file_path(meme_candidates, subfolders=["meme", "audio", ""])
    
    target_x, target_y = 740, 550
    box_w, box_h = 380, 235

    if meme_path and os.path.exists(meme_path):
        meme_raw = cv2.imread(meme_path)
        if meme_raw is not None:
            meme_resized = cv2.resize(meme_raw, (box_w, box_h))
            cert[target_y:target_y + box_h, target_x:target_x + box_w] = meme_resized
            cv2.rectangle(cert, (target_x, target_y), (target_x + box_w, target_y + box_h), (0, 0, 180), 3)
    else:
        cv2.rectangle(cert, (target_x, target_y), (target_x + box_w, target_y + box_h), (140, 140, 140), 2)
        cv2.putText(cert, f"MEME: {meme_candidates[0]}", (target_x + 35, target_y + 110), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (100, 100, 100), 1)

    # Footer
    cv2.putText(cert, "CERTIFIED BY QR USELESS ANALYZER", (420, 820), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (50, 50, 50), 2)

    cv2.imwrite(os.path.join(BASE_DIR, "latest_qr_certificate.png"), cert)
    return cert


# ==========================================
# MAIN APPLICATION LOOP
# ==========================================

def main():
    camera = cv2.VideoCapture(0)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    analyzed = False
    result = None
    scan_line_offset = 0

    cv2.namedWindow("QR Useless Analyzer", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("QR Useless Analyzer", 960, 720)

    while True:
        ret, frame = camera.read()
        if not ret:
            break

        key = cv2.waitKey(1) & 0xFF

        if not analyzed:
            decoded_objects = zbar_decode(frame)
            found = len(decoded_objects) > 0

            if found:
                obj = decoded_objects[0]
                pts = np.array(obj.polygon, dtype=np.int32)
                
                if len(pts) != 4:
                    x, y, w, h = obj.rect
                    pts = np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.int32)

                for i in range(4):
                    cv2.line(frame, tuple(pts[i]), tuple(pts[(i + 1) % 4]), (0, 255, 120), 2)
                    cv2.circle(frame, tuple(pts[i]), 5, (0, 255, 255), -1)

                top_y = np.min(pts[:, 1])
                bot_y = np.max(pts[:, 1])
                left_x = np.min(pts[:, 0])
                right_x = np.max(pts[:, 0])
                
                scan_line_offset += 10
                if bot_y > top_y:
                    curr_y = int(top_y + (scan_line_offset % (bot_y - top_y)))
                    cv2.line(frame, (left_x, curr_y), (right_x, curr_y), (0, 0, 255), 2)

                cv2.putText(frame, "TARGET LOCKED - PRESS [SPACE]", (30, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 100), 2)

                decoded_str = obj.data.decode("utf-8", errors="ignore")
                purpose_tag = "PAYLOAD"
                if decoded_str.lower().startswith("upi://"):
                    purpose_tag = "UPI PAYMENT"
                elif "WIFI:" in decoded_str.upper():
                    purpose_tag = "WI-FI HOTSPOT"
                elif decoded_str.lower().startswith("http"):
                    purpose_tag = "WEBSITE LINK"

                cv2.putText(frame, f"[{purpose_tag}] {decoded_str[:32]}...", (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 1)

                if key == 32:  # SPACE BAR
                    run_dramatic_loading_sequence(frame, "QR Useless Analyzer")

                    data = analyze_qr(frame, pts.astype(np.float32), decoded_str)
                    if data is not None:
                        result = data
                        analyzed = True

                        play_retro_scan_sound()
                        play_roast_clip_async(data["audio_category"])

                        cv2.namedWindow("QR Module Grid", cv2.WINDOW_NORMAL)
                        cv2.imshow("QR Module Grid", data["grid_visual"])

                        cert = create_certificate(data)
                        cv2.namedWindow("QR Certificate of Analysis", cv2.WINDOW_NORMAL)
                        cv2.resizeWindow("QR Certificate of Analysis", 1200, 850)
                        cv2.imshow("QR Certificate of Analysis", cert)
            else:
                cv2.putText(frame, "SHOW QR CODE", (30, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 100, 255), 2)

        else:
            cv2.putText(frame, "ANALYSIS COMPLETE! [R] RESET  [Q] QUIT", (30, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(frame, f"Purpose: {result['purpose']}", (30, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.putText(frame, f"Grid: {result['grid_size']}x{result['grid_size']} (V{result['version']})", (30, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1)
            cv2.putText(frame, f"Blocks: {result['black_squares']} Blk / {result['white_squares']} Wht", (30, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1)

        cv2.imshow("QR Useless Analyzer", frame)

        if key == ord('r'):
            analyzed = False
            result = None
            try:
                cv2.destroyWindow("QR Module Grid")
                cv2.destroyWindow("QR Certificate of Analysis")
            except Exception:
                pass
        elif key == ord('q'):
            break

    camera.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()