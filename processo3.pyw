"""Entrada do programa, com mensagem de erro mesmo ao abrir sem console."""
import traceback

if __name__ == "__main__":
    try:
        from coeficientes_app import main
        main()
    except Exception:
        detail = traceback.format_exc()
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Processo 3 — não foi possível iniciar",
                "Abra EXECUTAR_EM_PYTHON.bat para preparar o ambiente.\n\n" + detail[-2200:], parent=root)
            root.destroy()
        except Exception:
            print(detail)
        raise SystemExit(1)
