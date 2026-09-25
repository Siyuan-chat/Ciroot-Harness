import ctypes

from research_harness.gui.desktop import main

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None, str(exc), "CirootHarness 启动失败", 0x10)
        raise
