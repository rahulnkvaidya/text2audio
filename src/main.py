
import tkinter as tk
from tkinter import scrolledtext, messagebox, Menu, Toplevel, Label, Entry, Button
import json
import os
import azure.cognitiveservices.speech as speechsdk
from datetime import datetime

CONFIG_FILE = 'config.json'
OUTPUT_DIR = 'tts_outputs'

class ConfigWindow(Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Configure API Key")
        self.geometry("400x150")
        self.parent = parent

        Label(self, text="Azure Speech API Key:").pack(pady=5)
        self.api_key_entry = Entry(self, width=50)
        self.api_key_entry.pack(padx=10)

        Label(self, text="Azure Speech Region:").pack(pady=5)
        self.region_entry = Entry(self, width=50)
        self.region_entry.pack(padx=10)

        Button(self, text="Save", command=self.save_config).pack(pady=10)

        self.load_config_to_entries()

    def load_config_to_entries(self):
        config = self.parent.load_config()
        self.api_key_entry.insert(0, config.get('api_key', ''))
        self.region_entry.insert(0, config.get('region', ''))

    def save_config(self):
        config = {
            'api_key': self.api_key_entry.get(),
            'region': self.region_entry.get()
        }
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f)
            messagebox.showinfo("Success", "Configuration saved successfully!", parent=self)
            self.destroy()
        except IOError as e:
            messagebox.showerror("Error", f"Failed to save config file: {e}", parent=self)

class Application(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.master.title("Text-to-Audio (Azure TTS)")
        self.master.geometry("600x400")
        self.pack(fill=tk.BOTH, expand=True)
        self.create_widgets()
        self.create_menu()
        self.ensure_output_dir()

    def create_widgets(self):
        self.text_input = scrolledtext.ScrolledText(self, wrap=tk.WORD, height=15, width=70)
        self.text_input.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

        self.convert_button = Button(self, text="Convert to Audio", command=self.convert_text_to_speech)
        self.convert_button.pack(pady=5)

        self.status_label = Label(self, text="Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

    def create_menu(self):
        menubar = Menu(self.master)
        self.master.config(menu=menubar)

        file_menu = Menu(menubar, tearoff=0)
        file_menu.add_command(label="Exit", command=self.master.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        settings_menu = Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Configure API Key", command=self.open_config_window)
        menubar.add_cascade(label="Settings", menu=settings_menu)

    def open_config_window(self):
        ConfigWindow(self)

    def load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
        except (IOError, json.JSONDecodeError):
            return {}
        return {}

    def ensure_output_dir(self):
        if not os.path.exists(OUTPUT_DIR):
            os.makedirs(OUTPUT_DIR)

    def convert_text_to_speech(self):
        text = self.text_input.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("Input Error", "Please enter some text to convert.")
            return

        config_data = self.load_config()
        api_key = config_data.get('api_key')
        region = config_data.get('region')

        if not api_key or not region:
            messagebox.showerror("Configuration Error", "Azure API Key and Region are not configured. Please set them in Settings -> Configure API Key.")
            return

        self.status_label.config(text="Converting...")
        self.master.update_idletasks()

        try:
            speech_config = speechsdk.SpeechConfig(subscription=api_key, region=region)
            
            # Use a filename-safe version of the text for the output file
            safe_text = "".join(c for c in text[:30] if c.isalnum() or c in (' ','.','_')).rstrip()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = os.path.join(OUTPUT_DIR, f"{safe_text}_{timestamp}.mp3")
            
            audio_config = speechsdk.audio.AudioOutputConfig(filename=output_filename)
            
            # To use a specific voice
            # speech_config.speech_synthesis_voice_name = "en-US-JennyNeural"
            
            synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
            
            result = synthesizer.speak_text_async(text).get()

            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                self.status_label.config(text=f"Successfully saved to {output_filename}")
                messagebox.showinfo("Success", f"Audio file saved successfully in '{OUTPUT_DIR}' folder.")
            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation_details = result.cancellation_details
                error_message = f"Speech synthesis canceled: {cancellation_details.reason}"
                if cancellation_details.reason == speechsdk.CancellationReason.Error:
                    if cancellation_details.error_details:
                        error_message += f"\nError details: {cancellation_details.error_details}"
                self.status_label.config(text="Conversion failed.")
                messagebox.showerror("Error", error_message)

        except Exception as e:
            self.status_label.config(text="An error occurred.")
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = Application(master=root)
    app.mainloop()
