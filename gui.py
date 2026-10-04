"""Small tkinter front end; conversion stays offline and output is never overwritten."""
from pathlib import Path
from queue import Queue, Empty
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser

from generate_pet import generate, resolve_rows, TIMINGS, VERSION


def launch():
    root = tk.Tk()
    root.title(f"Pony Codex Pet Generator {VERSION}")
    root.geometry("840x700")
    root.minsize(760, 680)
    panel = ttk.Frame(root, padding=18)
    panel.pack(fill="both", expand=True)
    panel.columnconfigure(1, weight=1)
    variables = {k: tk.StringVar(value=v) for k, v in {
        "source": "", "output": str(Path.cwd() / "output" / "my-pony"),
        "name": "My Pony", "id": "my-pony", "description": "Pony Town companion", "facing": "right",
    }.items()}
    status = tk.StringVar(value="选择一个角色的透明 GIF 文件夹 / Select a transparent GIF folder")
    selected, frame_vars, mirror_vars = {}, {}, {}
    widgets = []
    messages = Queue()
    busy = False
    last_output = None

    def browse_source():
        directory = filedialog.askdirectory(parent=root)
        if not directory:
            return
        variables["source"].set(directory)
        auto_map()

    def browse_output():
        directory = filedialog.askdirectory(parent=root, title="选择输出父目录 / Output parent folder")
        if directory:
            variables["output"].set(str(Path(directory) / variables["id"].get()))

    for row, (key, label) in enumerate((
        ("source", "GIF 文件夹 / Source"), ("output", "新输出目录 / New output"),
        ("name", "桌宠名称 / Name"), ("id", "桌宠 ID / ID"), ("description", "简介 / Description"),
    )):
        ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", pady=5)
        entry = ttk.Entry(panel, textvariable=variables[key])
        entry.grid(row=row, column=1, columnspan=2, sticky="ew", padx=8)
        widgets.append(entry)
        if key in ("source", "output"):
            button = ttk.Button(panel, text="选择 / Browse", command=browse_source if key == "source" else browse_output)
            button.grid(row=row, column=3)
            widgets.append(button)
    ttk.Label(panel, text="素材朝向 / Source facing").grid(row=5, column=0, sticky="w")
    facing = ttk.Combobox(panel, textvariable=variables["facing"], values=("right", "left"), state="readonly", width=12)
    facing.grid(row=5, column=1, sticky="w", padx=8)
    widgets.append(facing)
    auto_button = ttk.Button(panel, text="自动匹配 / Auto match", command=lambda: auto_map())
    auto_button.grid(row=5, column=2, columnspan=2, pady=8)
    widgets.append(auto_button)
    for col, label in enumerate(("状态 / State", "GIF", "帧索引 / Frames (optional)", "镜像 / Mirror")):
        ttk.Label(panel, text=label).grid(row=6, column=col, sticky="w", pady=8)
    for row, state in enumerate(TIMINGS, start=7):
        ttk.Label(panel, text=state).grid(row=row, column=0, sticky="w", pady=3)
        selected[state] = tk.StringVar()
        combo = ttk.Combobox(panel, textvariable=selected[state], state="readonly", width=35)
        combo.grid(row=row, column=1, sticky="ew", padx=8)
        frame_vars[state] = tk.StringVar()
        entry = ttk.Entry(panel, textvariable=frame_vars[state], width=20)
        entry.grid(row=row, column=2)
        mirror_vars[state] = tk.BooleanVar(value=state == "running-left")
        check = ttk.Checkbutton(panel, variable=mirror_vars[state])
        check.grid(row=row, column=3)
        widgets.extend((combo, entry, check))
    ttk.Label(panel, text="帧索引从 0 开始，用逗号分隔；留空自动采样。所有动作使用同一缩放比例。",
              wraplength=780).grid(row=16, column=0, columnspan=4, sticky="w", pady=10)
    ttk.Label(panel, textvariable=status, wraplength=780).grid(row=17, column=0, columnspan=4, sticky="w", pady=8)

    def auto_map():
        try:
            source = Path(variables["source"].get())
            names = sorted(p.name for p in source.iterdir() if p.suffix.lower() == ".gif")
            for widget in widgets:
                if isinstance(widget, ttk.Combobox) and widget is not facing:
                    widget.configure(values=names)
            rows, warnings = resolve_rows(source)
            for state, path, _, mirror in rows:
                selected[state].set(path.name)
                frame_vars[state].set("")
                mirror_vars[state].set(mirror)
            status.set("匹配完成 / Matched. " + (" ".join(warnings) if warnings else ""))
        except (ValueError, OSError) as error:
            # Keep dropdowns usable for folders whose names require manual mapping.
            status.set(str(error) + " 可手动选择各动作 GIF / Select GIFs manually.")

    def start():
        nonlocal busy
        try:
            mapping = {}
            for state in TIMINGS:
                spec = {"file": selected[state].get(), "mirror": mirror_vars[state].get()}
                text = frame_vars[state].get().strip()
                if text:
                    spec["frames"] = [int(x.strip()) for x in text.split(",")]
                mapping[state] = spec
            values = {key: value.get() for key, value in variables.items()}
        except ValueError:
            messagebox.showerror("Frames", "帧索引必须是逗号分隔的整数 / Use comma-separated integers.")
            return
        busy = True
        for widget in widgets:
            widget.configure(state="disabled")
        status.set("正在生成 / Generating…")

        def worker():
            try:
                report = generate(values["source"], values["output"], values["name"], values["id"],
                                  values["description"], mapping=mapping, facing=values["facing"])
                messages.put((True, values["output"], report["warnings"]))
            except Exception as error:
                messages.put((False, str(error), []))
        threading.Thread(target=worker, daemon=True).start()

    def poll():
        nonlocal busy, last_output
        try:
            success, result, warnings = messages.get_nowait()
        except Empty:
            root.after(100, poll)
            return
        busy = False
        for widget in widgets:
            widget.configure(state="readonly" if isinstance(widget, ttk.Combobox) else "normal")
        if success:
            last_output = Path(result).resolve()
            status.set(f"完成 / Created: {result}" + ("\n" + " ".join(warnings) if warnings else ""))
            messagebox.showinfo("完成 / Done", "已生成图集、ZIP 和预览。安装步骤见 README；不会自动替换现有桌宠。")
        else:
            status.set(result)
            messagebox.showerror("生成失败 / Failed", result)
        root.after(100, poll)

    generate_button = ttk.Button(panel, text="生成桌宠 / Generate pet", command=start)
    generate_button.grid(row=18, column=1, pady=12, sticky="ew")
    widgets.append(generate_button)
    preview_button = ttk.Button(panel, text="打开预览 / Open preview", command=lambda:
                                webbrowser.open((last_output / "preview.html").as_uri()) if last_output else None)
    preview_button.grid(row=18, column=2, padx=8)
    widgets.append(preview_button)

    def close():
        if not busy or messagebox.askyesno("退出 / Exit", "正在生成，退出可能中断。仍要退出吗？ / Conversion is running. Exit?"):
            root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    root.after(100, poll)
    root.mainloop()


if __name__ == "__main__":
    launch()
