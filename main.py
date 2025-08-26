import os
import re
import sys
import json
import shutil
import queue
import hashlib
import sqlite3
import threading
import time
import random
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import requests
import subprocess

# ------------------------------
# App path helper
# ------------------------------
def get_app_dir():
    if getattr(sys, 'frozen', False):
        # Running as a bundled exe
        return os.path.dirname(sys.executable)
    else:
        # Running as a script
        return os.path.dirname(__file__)

APP_DIR = get_app_dir()
DB_PATH = os.path.join(APP_DIR, "tts_app.db")
AUDIO_OUTPUT_DIR = os.path.join(APP_DIR, "tts_outputs")

# ------------------------------
# SQLite storage
# ------------------------------
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id=1),
            api_key TEXT,
            region TEXT,
            endpoint TEXT,
            default_folder TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tts_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            text TEXT NOT NULL,
            voice TEXT NOT NULL,
            style TEXT NOT NULL,
            output_format TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            file_path TEXT NOT NULL
        )
    """)
    # seed single settings row if not present
    cur.execute("SELECT COUNT(*) FROM settings WHERE id=1")
    if cur.fetchone()[0] == 0:
        # Default values from your message (can be changed in Settings dialog)
        cur.execute("""
            INSERT INTO settings (id, api_key, region, endpoint, default_folder)
            VALUES (1, ?, ?, ?, ?)
        """, (
            "",  # keep blank by default; fill in Settings
            "northcentralus",
            "https://northcentralus.tts.speech.microsoft.com/cognitiveservices/v1",
            AUDIO_OUTPUT_DIR
        ))
    con.commit()
    con.close()

def load_settings():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT api_key, region, endpoint, default_folder FROM settings WHERE id=1")
    row = cur.fetchone()
    con.close()
    if not row:
        return {"api_key": "", "region": "northcentralus",
                "endpoint": "https://northcentralus.tts.speech.microsoft.com/cognitiveservices/v1",
                "default_folder": AUDIO_OUTPUT_DIR}
    return {"api_key": row[0] or "", "region": row[1] or "northcentralus",
            "endpoint": row[2] or "https://northcentralus.tts.speech.microsoft.com/cognitiveservices/v1",
            "default_folder": row[3]}

def save_settings(api_key, region, endpoint, default_folder):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        UPDATE settings SET api_key=?, region=?, endpoint=?, default_folder=? WHERE id=1
    """, (api_key, region, endpoint, default_folder))
    con.commit()
    con.close()

def add_history(text, voice, style, output_format, content_hash, file_path):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO tts_history (created_at, text, voice, style, output_format, content_hash, file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text, voice, style, output_format, content_hash, file_path))
    con.commit()
    con.close()

def find_history_by_hash(content_hash):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        SELECT id, created_at, text, voice, style, output_format, content_hash, file_path
        FROM tts_history WHERE content_hash=?
        ORDER BY id DESC
    """, (content_hash,))
    rows = cur.fetchall()
    con.close()
    return rows

def list_history():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        SELECT id, created_at, voice, style, output_format, file_path, substr(text,1,80) || CASE WHEN length(text)>80 THEN '…' ELSE '' END AS preview
        FROM tts_history ORDER BY id DESC
    """)
    rows = cur.fetchall()
    con.close()
    return rows

def get_history_item(item_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        SELECT id, created_at, text, voice, style, output_format, content_hash, file_path
        FROM tts_history WHERE id=?
    """, (item_id,))
    row = cur.fetchone()
    con.close()
    return row

def delete_history_item(item_id):
    row = get_history_item(item_id)
    if row:
        _, _, _, _, _, _, _, file_path = row
        # delete file if still exists
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("DELETE FROM tts_history WHERE id=?", (item_id,))
        con.commit()
        con.close()

# ------------------------------
# TTS helpers
# ------------------------------

# Voice options (language + gender)
VOICES = {
    "Hindi - Male (Madhur)": ("hi-IN", "Male", "hi-IN-MadhurNeural"),
    "Hindi - Female (Swara)": ("hi-IN", "Female", "hi-IN-SwaraNeural"),
    "English - Male (Guy)": ("en-US", "Male", "en-US-GuyNeural"),
    "English - Female (Aria)": ("en-US", "Female", "en-US-AriaNeural"),
}

STYLES = ["default", "cheerful", "sad", "angry", "excited", "empathetic"]
OUTPUT_FORMAT = "audio-48khz-192kbitrate-mono-mp3"
FILE_EXT = ".mp3"

PAUSE_TOKEN_REGEX = re.compile(r"\[p-(\d+)\]")  # e.g. [p-2] => 2s

def to_ssml(text, lang, gender, voice_name, style):
    # Replace [p-<n>] with SSML break
    def repl(m):
        seconds = m.group(1)
        return f"<break time='{seconds}s'/>"
    safe_text = PAUSE_TOKEN_REGEX.sub(repl, text)
    ssml_template = '''
<speak version='1.0' xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang='{lang}'>
  <voice xml:lang='{lang}' xml:gender='{gender}' name='{voice_name}'>
    <mstts:express-as style="{style}">
      {safe_text}
    </mstts:express-as>
  </voice>
</speak>
'''
    ssml = ssml_template.format(
        lang=lang,
        gender=gender,
        voice_name=voice_name,
        style=style,
        safe_text=safe_text
    )
    return ssml.strip()

def compute_hash(text, voice_key, style, output_format):
    h = hashlib.sha256()
    payload = json.dumps({
        "text": text, "voice_key": voice_key, "style": style, "fmt": output_format
    }, ensure_ascii=False).encode("utf-8")
    h.update(payload)
    return h.hexdigest()

def ensure_folder(path):
    os.makedirs(path, exist_ok=True)
    return path

def sanitize_filename(name):
    name = re.sub(r"[^\w\s.-]", "", name, flags=re.UNICODE).strip()
    name = re.sub(r"\s+", "_", name)
    return name or "audio"

def default_output_path(base_folder, text_preview):
    ensure_folder(base_folder)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = sanitize_filename(text_preview[:40]) + "_" + stamp + FILE_EXT
    return os.path.join(base_folder, fname)

def open_file_cross_platform(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception as e:
        messagebox.showerror("Open Error", str(e))

# ------------------------------
# GUI
# ------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Text-to-Audio")
        self.geometry("860x640")
        self.minsize(820, 600)

        init_db()
        self.settings = load_settings()
        ensure_folder(self.settings["default_folder"])

        # Menu
        menubar = tk.Menu(self)
        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Settings…", command=self.open_settings)
        settings_menu.add_separator()
        settings_menu.add_command(label="History…", command=self.open_history)
        menubar.add_cascade(label="Menu", menu=settings_menu)
        self.config(menu=menubar)

        # Top controls
        top = ttk.Frame(self)
        top.pack(fill="x", padx=12, pady=8)

        ttk.Label(top, text="Voice:").grid(row=0, column=0, sticky="w", padx=(0,6))
        self.voice_var = tk.StringVar(value=list(VOICES.keys())[0])
        self.voice_combo = ttk.Combobox(top, textvariable=self.voice_var, state="readonly",
                                        values=list(VOICES.keys()), width=30)
        self.voice_combo.grid(row=0, column=1, sticky="w")

        ttk.Label(top, text="Style:").grid(row=0, column=2, sticky="w", padx=(18,6))
        self.style_var = tk.StringVar(value=STYLES[0])
        self.style_combo = ttk.Combobox(top, textvariable=self.style_var, state="readonly",
                                        values=STYLES, width=18)
        self.style_combo.grid(row=0, column=3, sticky="w")

        # Pause buttons
        pause_bar = ttk.Frame(self)
        pause_bar.pack(fill="x", padx=12, pady=(0,6))
        ttk.Label(pause_bar, text="Insert Pause at cursor:").pack(side="left")
        for sec in [1, 2, 3, 5]:
            ttk.Button(pause_bar, text=f"[p-{sec}]", command=lambda s=sec: self.insert_pause(s)).pack(side="left", padx=4)

        # Text area
        text_frame = ttk.Frame(self)
        text_frame.pack(fill="both", expand=True, padx=12, pady=6)
        ttk.Label(text_frame, text="Enter Text:").pack(anchor="w")
        self.text = tk.Text(text_frame, wrap="word", height=18)
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", "नमस्ते! यह एक डेमो है। [p-1] आप कैसे हैं?")

        # Bottom controls
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=12, pady=8)

        self.progress = ttk.Progressbar(bottom, orient="horizontal", mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(0,8))

        # status label to show text status
        self.status_label = ttk.Label(bottom, text="Status: Idle")
        self.status_label.pack(side="left", padx=(8,12))

        ttk.Button(bottom, text="Convert & Save", command=self.convert_and_save).pack(side="right")
        ttk.Button(bottom, text="Preview / Open Last File", command=self.open_last_file).pack(side="right", padx=(0,8))
        ttk.Button(bottom, text="History", command=self.open_history).pack(side="right", padx=(0,8))

        self.last_saved_file = None

    # ---- UX helpers ----
    def insert_pause(self, seconds):
        token = f"[p-{seconds}]"
        pos = self.text.index(tk.INSERT)
        self.text.insert(pos, token)

    # thread-safe UI setters
    def set_progress(self, val):
        def _set():
            self.progress["value"] = max(0, min(100, val))
        self.after(0, _set)

    def set_status(self, text):
        def _set():
            self.status_label.config(text=text)
        self.after(0, _set)

    def safe_info(self, title, msg):
        self.after(0, lambda: messagebox.showinfo(title, msg))

    def safe_error(self, title, msg):
        self.after(0, lambda: messagebox.showerror(title, msg))

    # ---- TTS workflow (fixed progress) ----
    def convert_and_save(self):
        text_val = self.text.get("1.0", "end-1c").strip()
        if not text_val:
            messagebox.showerror("Error", "कृपया कुछ टेक्स्ट दर्ज करें।")
            return

        voice_key = self.voice_var.get()
        if voice_key not in VOICES:
            messagebox.showerror("Error", "कृपया एक वैध voice चुनें।")
            return
        lang, gender, voice_name = VOICES[voice_key]
        style = self.style_var.get()

        # Decide output folder (from Settings)
        base_folder = self.settings.get("default_folder") or AUDIO_OUTPUT_DIR
        ensure_folder(base_folder)
        proposed_path = default_output_path(base_folder, text_val)

        # Check duplicates
        content_hash = compute_hash(text_val, voice_key, style, OUTPUT_FORMAT)
        dup_rows = find_history_by_hash(content_hash)
        for r in dup_rows:
            _, _, _, v, st, fmt, h, path = r
            if os.path.exists(path):
                # Reuse
                self.last_saved_file = path
                messagebox.showinfo("Already Exists", f"उसी टेक्स्ट/वॉइस/स्टाइल की फ़ाइल पहले से मौजूद है:\n{path}\n\nनई फ़ाइल नहीं बनाई गई।")
                return

        # Ask save path (allow user to override file name)
        save_path = filedialog.asksaveasfilename(
            initialdir=base_folder,
            initialfile=os.path.basename(proposed_path),
            defaultextension=FILE_EXT,
            filetypes=[("MP3 Audio", f"*{FILE_EXT}")]
        )
        if not save_path:
            return

        # Settings check
        sett = load_settings()
        api_key = sett["api_key"].strip()
        endpoint = (sett["endpoint"] or "").strip()

        if not api_key:
            messagebox.showerror("Missing API Key", "Settings में API Key जोड़ें।")
            return
        if not endpoint:
            messagebox.showerror("Missing Endpoint", "Settings में Endpoint जोड़ें (e.g., https://<region>.tts.speech.microsoft.com/cognitiveservices/v1).")
            return

        # Prepare SSML
        ssml = to_ssml(text_val, lang, gender, voice_name, style)

        headers = {
            "Ocp-Apim-Subscription-Key": api_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": OUTPUT_FORMAT
        }

        # Reset UI
        self.set_progress(5)
        self.set_status("Converting... (starting)")

        # Event to signal completion
        done_event = threading.Event()
        error_holder = {"error": None}

        # Progress updater thread (shows liveliness while request is ongoing)
        def progress_updater():
            # start from current progress
            while not done_event.is_set():
                # increase progress with smaller random steps but cap at 90
                cur = self.progress["value"]
                if cur < 90:
                    cur += random.randint(3, 8)
                    self.set_progress(cur)
                # update status message little by little
                # use dots effect
                self.set_status("Converting... (in progress)")
                time.sleep(0.5)
            # once done, ensure progress goes to 100 or 0 on error
            if error_holder["error"] is None:
                self.set_progress(100)
                self.set_status("Completed ✅")
            else:
                self.set_progress(0)
                self.set_status("Failed ❌")

        def worker():
            try:
                # indicate some progress
                self.set_progress(20)
                self.set_status("Converting... (requesting)")
                resp = requests.post(endpoint, headers=headers, data=ssml.encode("utf-8"), timeout=120)
                self.set_progress(70)
                if resp.status_code == 200:
                    with open(save_path, "wb") as f:
                        f.write(resp.content)
                    self.last_saved_file = save_path
                    add_history(text_val, voice_key, style, OUTPUT_FORMAT, content_hash, save_path)
                    error_holder["error"] = None
                    done_event.set()
                    # show info from main thread
                    self.safe_info("Success", f"Saved:\n{save_path}")
                else:
                    error_holder["error"] = f"HTTP {resp.status_code}: {resp.text}"
                    done_event.set()
                    self.safe_error("TTS Error", f"HTTP {resp.status_code}\n{resp.text}")
            except Exception as e:
                error_holder["error"] = str(e)
                done_event.set()
                self.safe_error("Exception", str(e))

        # start threads
        t_progress = threading.Thread(target=progress_updater, daemon=True)
        t_worker = threading.Thread(target=worker, daemon=True)
        t_progress.start()
        t_worker.start()

    def open_last_file(self):
        if not self.last_saved_file or not os.path.exists(self.last_saved_file):
            messagebox.showinfo("Info", "अभी कोई recent फ़ाइल नहीं मिली। History से खोलें।")
            return
        open_file_cross_platform(self.last_saved_file)

    # ---- Settings dialog ----
    def open_settings(self):
        sett = load_settings()
        win = tk.Toplevel(self)
        win.title("Settings")
        win.geometry("560x280")
        win.transient(self)
        win.grab_set()

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="API Key:").grid(row=0, column=0, sticky="e", pady=6, padx=6)
        api_var = tk.StringVar(value=sett["api_key"])
        ttk.Entry(frm, textvariable=api_var, show="•", width=52).grid(row=0, column=1, sticky="we")

        ttk.Label(frm, text="Region:").grid(row=1, column=0, sticky="e", pady=6, padx=6)
        region_var = tk.StringVar(value=sett["endpoint"].split("//")[1].split(".")[0] if sett["endpoint"] else "northcentralus")
        ttk.Entry(frm, textvariable=region_var, width=52).grid(row=1, column=1, sticky="we")

        ttk.Label(frm, text="Endpoint:").grid(row=2, column=0, sticky="e", pady=6, padx=6)
        ep_var = tk.StringVar(value=sett["endpoint"])
        ttk.Entry(frm, textvariable=ep_var, width=52).grid(row=2, column=1, sticky="we")

        ttk.Label(frm, text="Default Save Folder:").grid(row=3, column=0, sticky="e", pady=6, padx=6)
        folder_var = tk.StringVar(value=sett["default_folder"])
        frow = ttk.Frame(frm)
        frow.grid(row=3, column=1, sticky="we")
        e = ttk.Entry(frow, textvariable=folder_var, width=42)
        e.pack(side="left", fill="x", expand=True)
        def browse_folder():
            p = filedialog.askdirectory(initialdir=folder_var.get() or os.getcwd())
            if p:
                folder_var.set(p)
        ttk.Button(frow, text="Browse", command=browse_folder).pack(side="left", padx=(6,0))

        btn_row = ttk.Frame(frm)
        btn_row.grid(row=4, column=0, columnspan=2, pady=12)
        def save_and_close():
            api_key = api_var.get().strip()
            region = region_var.get().strip() or "northcentralus"
            endpoint = ep_var.get().strip() or f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
            folder = folder_var.get().strip() or AUDIO_OUTPUT_DIR
            save_settings(api_key, region, endpoint, folder)
            self.settings = load_settings()
            ensure_folder(self.settings["default_folder"])
            messagebox.showinfo("Saved", "Settings updated.")
            win.destroy()
        ttk.Button(btn_row, text="Save", command=save_and_close).pack(side="right")
        ttk.Button(btn_row, text="Cancel", command=win.destroy).pack(side="right", padx=(0,8))

        for i in range(2):
            frm.columnconfigure(i, weight=1)

    # ---- History window ----
    def open_history(self):
        win = tk.Toplevel(self)
        win.title("History")
        win.geometry("920x460")
        win.transient(self)
        win.grab_set()

        cols = ("id", "created", "voice", "style", "format", "file", "preview")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for c, w in zip(cols,
                        [60, 140, 180, 110, 160, 260, 300]):
            tree.heading(c, text=c.title())
            tree.column(c, width=w, anchor="w")
        tree.pack(fill="both", expand=True, padx=8, pady=8)

        def refresh():
            tree.delete(*tree.get_children())
            for r in list_history():
                tree.insert("", "end", values=r)

        def get_selected_id():
            item = tree.focus()
            if not item:
                return None
            vals = tree.item(item, "values")
            return int(vals[0]) if vals else None

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=8, pady=(0,8))

        def play_selected():
            hid = get_selected_id()
            if not hid: return
            row = get_history_item(hid)
            if row:
                path = row[7]
                if os.path.exists(path):
                    open_file_cross_platform(path)
                else:
                    messagebox.showerror("Missing", "File not found on disk.")

        def download_selected():
            hid = get_selected_id()
            if not hid: return
            row = get_history_item(hid)
            if not row: return
            src = row[7]
            if not os.path.exists(src):
                messagebox.showerror("Missing", "File not found on disk.")
                return
            dst = filedialog.asksaveasfilename(defaultextension=FILE_EXT,
                                               initialfile=os.path.basename(src),
                                               filetypes=[("MP3 Audio", f"*{FILE_EXT}")])
            if not dst: return
            try:
                shutil.copy2(src, dst)
                messagebox.showinfo("Downloaded", f"Saved to:\n{dst}")
            except Exception as e:
                messagebox.showerror("Error", str(e))

        def delete_selected():
            hid = get_selected_id()
            if not hid: return
            if messagebox.askyesno("Delete", "Delete selected history and file?"):
                delete_history_item(hid)
                refresh()

        def update_regen():
            # allows editing text/voice/style then re-generate
            hid = get_selected_id()
            if not hid: return
            row = get_history_item(hid)
            if not row: return
            _, _, old_text, old_voice, old_style, _, _, old_path = row

            upd = tk.Toplevel(win)
            upd.title("Update & Re-generate")
            upd.geometry("760x560")
            upd.transient(win)
            upd.grab_set()

            ttk.Label(upd, text="Voice:").grid(row=0, column=0, sticky="e", padx=6, pady=6)
            v_var = tk.StringVar(value=old_voice)
            v_combo = ttk.Combobox(upd, textvariable=v_var, state="readonly", values=list(VOICES.keys()), width=32)
            v_combo.grid(row=0, column=1, sticky="w")

            ttk.Label(upd, text="Style:").grid(row=0, column=2, sticky="e", padx=6, pady=6)
            s_var = tk.StringVar(value=old_style)
            s_combo = ttk.Combobox(upd, textvariable=s_var, state="readonly", values=STYLES, width=20)
            s_combo.grid(row=0, column=3, sticky="w")

            ttk.Label(upd, text="Text:").grid(row=1, column=0, sticky="ne", padx=6, pady=6)
            t = tk.Text(upd, wrap="word", height=20)
            t.grid(row=1, column=1, columnspan=3, sticky="nsew", padx=(0,6), pady=6)
            t.insert("1.0", old_text)

            # pause quick insert buttons
            pbar = ttk.Frame(upd)
            pbar.grid(row=2, column=1, columnspan=3, sticky="w", padx=0, pady=(0,6))
            ttk.Label(pbar, text="Insert Pause:").pack(side="left")
            for sec in [1,2,3,5]:
                ttk.Button(pbar, text=f"[p-{sec}]", command=lambda s=sec: t.insert(tk.INSERT, f"[p-{s}]")).pack(side="left", padx=4)

            def do_regen():
                new_text = t.get("1.0", "end-1c").strip()
                if not new_text:
                    messagebox.showerror("Error", "Text empty.")
                    return
                voice_key = v_var.get()
                lang, gender, voice_name = VOICES[voice_key]
                style = s_var.get()

                # Check duplicate hash
                content_hash = compute_hash(new_text, voice_key, style, OUTPUT_FORMAT)
                dups = find_history_by_hash(content_hash)
                for r in dups:
                    path = r[7]
                    if os.path.exists(path):
                        messagebox.showinfo("Already Exists", f"Same content exists:\n{path}")
                        return

                # Use same folder as original file
                base_folder = os.path.dirname(old_path) if old_path and os.path.isdir(os.path.dirname(old_path)) else load_settings()["default_folder"]
                ensure_folder(base_folder)
                save_path = filedialog.asksaveasfilename(
                    initialdir=base_folder,
                    initialfile=os.path.basename(default_output_path(base_folder, new_text)),
                    defaultextension=FILE_EXT,
                    filetypes=[("MP3 Audio", f"*{FILE_EXT}")]
                )
                if not save_path: return

                sett = load_settings()
                api_key = sett["api_key"].strip()
                endpoint = (sett["endpoint"] or "").strip()
                if not api_key or not endpoint:
                    messagebox.showerror("Missing Settings", "API Key/Endpoint missing in Settings.")
                    return

                ssml = to_ssml(new_text, lang, gender, voice_name, style)
                headers = {
                    "Ocp-Apim-Subscription-Key": api_key,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": OUTPUT_FORMAT
                }
                try:
                    resp = requests.post(endpoint, headers=headers, data=ssml.encode("utf-8"), timeout=60)
                    if resp.status_code == 200:
                        with open(save_path, "wb") as f:
                            f.write(resp.content)
                        add_history(new_text, voice_key, style, OUTPUT_FORMAT, content_hash, save_path)
                        messagebox.showinfo("Success", f"Saved:\n{save_path}")
                        refresh()
                        upd.destroy()
                    else:
                        messagebox.showerror("TTS Error", f"HTTP {resp.status_code}\n{resp.text}")
                except Exception as e:
                    messagebox.showerror("Exception", str(e))

            btnrow = ttk.Frame(upd)
            btnrow.grid(row=3, column=0, columnspan=4, pady=10)
            ttk.Button(btnrow, text="Re-generate & Save", command=do_regen).pack(side="right")
            ttk.Button(btnrow, text="Cancel", command=upd.destroy).pack(side="right", padx=(0,8))

            upd.columnconfigure(1, weight=1)
            upd.columnconfigure(3, weight=1)
            upd.rowconfigure(1, weight=1)

        ttk.Button(btns, text="Play/Open", command=play_selected).pack(side="left")
        ttk.Button(btns, text="Download", command=download_selected).pack(side="left", padx=6)
        ttk.Button(btns, text="Update / Re-generate", command=update_regen).pack(side="left", padx=6)
        ttk.Button(btns, text="Delete", command=delete_selected).pack(side="left", padx=6)
        ttk.Button(btns, text="Refresh", command=refresh).pack(side="right")

        refresh()

# ------------------------------
# Run
# ------------------------------
if __name__ == "__main__":
    app = App()
    app.mainloop()
