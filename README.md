# Text-to-Audio (Azure TTS)

This is an open-source desktop application that converts text into speech using Microsoft Azure's Cognitive Services Speech API. It provides a simple graphical user interface (GUI) to enter text and save the generated audio as an MP3 file.

## Features

- Simple and easy-to-use interface.
- Converts text to high-quality speech using Azure TTS.
- Securely stores your Azure API Key and Region locally.
- Saves audio output as MP3 files.
- Cross-platform (should work on Windows, macOS, and Linux).

## Getting Started

### 1. How to Get Azure Speech API Key and Region

To use this application, you need an API Key and Region from the Microsoft Azure portal.

1.  **Log in to the Azure Portal:** Go to [https://portal.azure.com/](https://portal.azure.com/) and log in with your Microsoft account.

2.  **Create a Speech Service Resource:**
    *   Click on **"+ Create a resource"**.
    *   Search for **"Speech"** in the marketplace and select it.
    *   Click the **"Create"** button.
    *   Fill in the required details:
        *   **Subscription:** Choose your Azure subscription.
        *   **Resource group:** Create a new one (e.g., `TextToAudioResourceGroup`) or select an existing one.
        *   **Region:** Choose a region close to you (e.g., `East US`). **Remember this region name.**
        *   **Name:** Give your resource a unique name (e.g., `MyTextToAudioService`).
        *   **Pricing tier:** Select `Free F0` for a free tier with limitations, which is sufficient for this application.
    *   Click **"Review + create"** and then **"Create"**. Wait for the deployment to complete.

3.  **Get the API Key and Region:**
    *   Once deployed, click on **"Go to resource"**.
    *   In the left-hand menu, navigate to the **"Keys and Endpoint"** section under "Resource Management".
    *   You will see two keys (KEY 1 and KEY 2) and the Location/Region.
    *   Copy **KEY 1** and the **Region** value (e.g., `eastus`). You will need these for the application.

### 2. How to Use the Application

1.  **Run the application**.
2.  The first time you use it, you need to configure your Azure credentials:
    *   Go to the menu: **Settings -> Configure API Key**.
    *   Paste your copied Azure Speech **API Key** and **Region** into the respective fields.
    *   Click **"Save"**.
3.  **Enter Text:** Type or paste the text you want to convert into the main text box.
4.  **Convert:** Click the **"Convert to Audio"** button.
5.  **Listen:** The audio will be saved as an MP3 file in the `tts_outputs` folder, located in the same directory as the application.

## How to Build the Executable (`.exe`)

You can package this application into a single executable file for easy distribution on Windows.

### Prerequisites

- [Python](https://www.python.org/downloads/) installed on your system. Make sure to check "Add Python to PATH" during installation.
- The project files downloaded to your computer.

### Build Steps

1.  **Open a Command Prompt or Terminal**.

2.  **Navigate to the project directory** where `main.py` and `requirements.txt` are located:
    ```sh
    cd path\to\your\project\folder
    ```

3.  **Create a virtual environment** (recommended to avoid conflicts with other Python projects):
    ```sh
    python -m venv venv
    ```

4.  **Activate the virtual environment**:
    ```sh
    venv\Scripts\activate
    ```

5.  **Install the required libraries**:
    ```sh
    pip install -r requirements.txt
    ```

6.  **Install PyInstaller**, the tool used to create the executable:
    ```sh
    pip install pyinstaller
    ```

7.  **Run the PyInstaller build command**:
    *This command tells PyInstaller to create a single executable file (`--onefile`), prevent a console window from appearing in the background (`--windowed`), and give the executable a specific name.* 
    ```sh
    pyinstaller --onefile --windowed --name Text-to-Audio src/main.py
    ```

8.  **Find your executable**:
    *   The process will create a `dist` folder. 
    *   Inside the `dist` folder, you will find **`Text-to-Audio.exe`**. This is your standalone application that you can run or share.
