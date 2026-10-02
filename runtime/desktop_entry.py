import os


def main() -> None:
    os.environ.setdefault(
        "AGENT_MAN_ALLOWED_ORIGINS",
        ",".join(
            [
                "http://tauri.localhost",
                "https://tauri.localhost",
                "tauri://localhost",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ]
        ),
    )

    import uvicorn
    from app.main import app

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.getenv("AGENT_MAN_PORT", "8765")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
