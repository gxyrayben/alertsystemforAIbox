# Project Overview: 安防综合管理平台 (Security Management Platform)

This project is a modern security management platform built with a **FastAPI** backend and a **Svelte** frontend. It provides features for device management, security alert monitoring with AI-assisted analysis, and an AI chat assistant for administrative support.

## Architecture

-   **Backend:** FastAPI (Python)
    -   Location: `/backend`
    -   Key file: `main.py` (Single-file entry point for API and data models)
    -   Features: RESTful CRUD for devices, alert filtering, and simulated AI endpoints for analysis and chat.
-   **Frontend:** Svelte (TypeScript/JavaScript)
    -   Location: `/frontend`
    -   Key files:
        -   `src/App.svelte`: Main application logic and UI.
        -   `src/lib/Icon.svelte`: Modular SVG icon component.
    -   Styling: Tailwind CSS via CDN or local installation.

## Core Features

1.  **Device Management:** CRUD operations for security devices (e.g., cameras).
2.  **Alert Management:** Real-time alert monitoring with filtering capabilities and AI-driven analysis for generated alerts.
3.  **AI Assistant:** Integrated chat interface for querying platform-related information.

## Building and Running

### Backend (FastAPI)

1.  **Dependencies:** Ensure `fastapi`, `uvicorn`, and `pydantic` are installed.
    ```bash
    pip install fastapi uvicorn pydantic
    ```
2.  **Run Service:**
    ```bash
    cd backend
    python main.py
    ```
    Alternatively:
    ```bash
    python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
    ```
    The API will be accessible at `http://localhost:8000`.

### Frontend (Svelte)

1.  **Dependencies:**
    ```bash
    cd frontend
    npm install
    ```
2.  **Run Development Server:**
    ```bash
    npm run dev
    ```
    The UI will be accessible at `http://localhost:5173` (default Vite port).

## Development Conventions

-   **State Management:** Local component state in Svelte using `let` and `reactive` declarations (`$:`).
-   **API Communication:** Frontend communicates with the backend via `fetch` using the `API_BASE` constant.
-   **CORS:** Backend is configured to allow all origins (`*`) for development simplicity.
-   **Modular Icons:** SVG icons are centralized in `Icon.svelte` and rendered via `{@html ...}`.
