"""
画面コーチ(Windows常駐 画面記録ツール)

ホットキー(既定F9)で画面全体の録画(mp4)を開始/停止する。
別のホットキー(既定F10)で、指定した間隔ごとに自動でスクリーンショットを
撮り続けるモードを開始/停止する。録画とスクショ自動保存は独立していて、
同時に動かすことも、片方だけ動かすこともできる。

このツール自体はAIと一切通信しない。録画・スクショをフォルダに溜めておく
だけで、振り返りたい時にしゅんりさんが山田くん(Claude Code)との会話の中で、
保存されたフォルダの画像・動画を直接見せて相談する、という運用を想定している。
"""

import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog

import cv2
import keyboard
import mss
import mss.tools
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG = {
    # 画面録画の開始/停止トグル
    "record_hotkey": "f9",
    # スクリーンショット自動保存の開始/停止トグル(録画とは独立して使える)
    "screenshot_hotkey": "f10",
    # 自動保存の間隔(秒)。画面上のプリセット(10/30/60)かカスタム値を指定できる
    "screenshot_interval_sec": 30,
    # 録画の1秒あたりコマ数。ゲームプレイ・勉強の振り返り用途なので
    # 高フレームレートは不要(ファイルサイズを抑える狙い)
    "video_fps": 8,
    # 保存先フォルダ。相対パスならこのmain.pyのあるフォルダから見た場所、
    # 絶対パスならそのまま使う
    "save_root": "セッション",
}

INTERVAL_PRESETS = [10, 30, 60]

# ---------- 見た目(ダーク×シアンのテーマ。音声入力ツールとは色味を変えて
# 「別のツール」と一目でわかるようにしている) ----------
BG = "#12181c"
PANEL = "#1a232a"
PANEL_DARK = "#0c1114"
ACCENT = "#3ecbff"
ACCENT_DIM = "#2b8fb8"
TEXT_MAIN = "#dff3fb"
TEXT_DIM = "#7d939e"
REC_RED = "#ff4b4b"
BORDER = "#2a3840"


def load_config():
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        import json
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = DEFAULT_CONFIG.copy()
        cfg.update(data)
        return cfg
    except Exception:
        return DEFAULT_CONFIG.copy()


def save_config(cfg):
    import json
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def resolve_save_root(cfg):
    root = cfg.get("save_root", DEFAULT_CONFIG["save_root"])
    if not os.path.isabs(root):
        root = os.path.join(BASE_DIR, root)
    return root


def get_primary_monitor(sct):
    """mssのmonitors[0]は複数モニターをまとめた仮想スクリーン全体なので、
    通常はプライマリモニター(monitors[1])だけを対象にする。
    モニターが1台しか無い環境ではmonitors[1]が無いのでmonitors[0]を使う。"""
    return sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]


def save_screenshot(sct, monitor, folder):
    """今の画面を1枚PNGで保存し、保存したパスを返す(ロジックだけを
    tkinterから切り離してあるので、GUI無しでも単体テストできる)。"""
    os.makedirs(folder, exist_ok=True)
    img = sct.grab(monitor)
    filename = time.strftime("%Y%m%d_%H%M%S") + ".png"
    path = os.path.join(folder, filename)
    if os.path.exists(path):
        # 同じ秒に2回撮った場合の上書き防止
        filename = time.strftime("%Y%m%d_%H%M%S_") + f"{time.time_ns() % 1000000}.png"
        path = os.path.join(folder, filename)
    mss.tools.to_png(img.rgb, img.size, output=path)
    return path


class ScreenRecorder:
    """画面全体をmp4で録画する(mss+OpenCV、別スレッドで動く)。"""

    def __init__(self, fps):
        self.fps = fps
        self._thread = None
        self._stop_event = threading.Event()
        self.start_time = None
        self.last_error = None

    @property
    def active(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, path):
        self._stop_event.clear()
        self.last_error = None
        self.start_time = time.time()
        self._thread = threading.Thread(target=self._run, args=(path,), daemon=True)
        self._thread.start()

    def _run(self, path):
        try:
            with mss.MSS() as sct:
                monitor = get_primary_monitor(sct)
                width, height = monitor["width"], monitor["height"]
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(path, fourcc, self.fps, (width, height))
                if not writer.isOpened():
                    self.last_error = "動画ファイルを作成できませんでした"
                    return
                interval = 1.0 / self.fps
                next_frame_at = time.time()
                try:
                    while not self._stop_event.is_set():
                        frame = np.array(sct.grab(monitor))
                        writer.write(cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR))
                        next_frame_at += interval
                        wait = next_frame_at - time.time()
                        if wait > 0:
                            self._stop_event.wait(wait)
                        else:
                            next_frame_at = time.time()
                finally:
                    writer.release()
        except Exception as e:
            self.last_error = str(e)

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def elapsed(self):
        if self.start_time is None or not self.active:
            return 0
        return time.time() - self.start_time


class ScreenshotTimer:
    """一定間隔でスクリーンショットを撮り続ける(別スレッドで動く)。"""

    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._count_lock = threading.Lock()
        self.count = 0
        self.last_path = None
        self.last_error = None

    @property
    def active(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, folder, interval_sec, reset_count=True):
        if reset_count:
            self.count = 0
            self.last_path = None
        self.last_error = None
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, args=(folder, interval_sec), daemon=True,
        )
        self._thread.start()

    def _run(self, folder, interval_sec):
        try:
            with mss.MSS() as sct:
                monitor = get_primary_monitor(sct)
                while not self._stop_event.is_set():
                    try:
                        path = save_screenshot(sct, monitor, folder)
                        self._note_shot(path)
                    except Exception as e:
                        self.last_error = str(e)
                    if self._stop_event.wait(interval_sec):
                        break
        except Exception as e:
            self.last_error = str(e)

    def _note_shot(self, path):
        with self._count_lock:
            self.count += 1
            self.last_path = path

    def add_manual_shot(self, path):
        """ホットキー/自動保存とは別に、ボタンで単発で撮った1枚を数に加える。"""
        self._note_shot(path)

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None


class App:
    def __init__(self):
        self.cfg = load_config()
        self.save_root = resolve_save_root(self.cfg)
        os.makedirs(self.save_root, exist_ok=True)

        self.recorder = ScreenRecorder(self.cfg.get("video_fps", 8))
        self.shot_timer = ScreenshotTimer()

        self.session_dir = None
        self.waiting_hotkey_capture = False
        self._capture_target = None
        self._last_toggle_time = 0.0
        self.events = queue.Queue()

        self.root = tk.Tk()
        self.root.title("画面コーチ")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        self._build_ui()
        self._register_hotkeys()
        self._refresh_hotkey_labels()
        self._update_interval_label()
        self._update_folder_label()
        self.status_var.set("待機中です。ホットキーかボタンで開始できます")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(200, self._poll)

    # ---------- セッションフォルダ ----------

    def _session_active(self):
        return self.recorder.active or self.shot_timer.active

    def _get_session_dir(self):
        """録画・スクショどちらかが動いている間は同じフォルダを使い回す。
        両方止まっている状態から次に始めた時だけ、新しい日時フォルダを作る
        (=ひとまとまりの作業セッションごとにフォルダが分かれる)。"""
        if self.session_dir is None:
            ts = time.strftime("%Y%m%d_%H%M%S")
            self.session_dir = os.path.join(self.save_root, ts)
            os.makedirs(self.session_dir, exist_ok=True)
        return self.session_dir

    def _maybe_close_session(self):
        if not self._session_active():
            self.session_dir = None
        self._update_folder_label()

    # ---------- UI構築 ----------

    def _build_ui(self):
        header = tk.Frame(self.root, bg=PANEL, height=52)
        header.pack(fill="x")
        tk.Label(
            header, text="画面コーチ", font=("Meiryo", 14, "bold"),
            bg=PANEL, fg=ACCENT,
        ).pack(side="left", padx=14, pady=8)
        tk.Label(
            header, text="画面を録画 / 一定間隔でスクショ保存",
            font=("Meiryo", 8), bg=PANEL, fg=TEXT_DIM,
        ).pack(side="left", pady=8)

        self._build_rec_indicator()
        self._build_record_panel()
        self._build_screenshot_panel()
        self._build_folder_panel()
        self._build_status_bar()

    def _build_rec_indicator(self):
        """一目で「今録画中か」がわかる大きめの表示。"""
        frame = tk.Frame(self.root, bg=BG)
        frame.pack(fill="x", padx=14, pady=(10, 0))

        self.rec_dot = tk.Canvas(
            frame, width=20, height=20, bg=BG, highlightthickness=0,
        )
        self.rec_dot.pack(side="left")
        self.rec_text_var = tk.StringVar(value="待機中")
        tk.Label(
            frame, textvariable=self.rec_text_var, font=("Consolas", 16, "bold"),
            bg=BG, fg=TEXT_MAIN,
        ).pack(side="left", padx=(8, 0))
        self.rec_timer_var = tk.StringVar(value="")
        tk.Label(
            frame, textvariable=self.rec_timer_var, font=("Consolas", 14),
            bg=BG, fg=TEXT_DIM,
        ).pack(side="left", padx=(10, 0))
        self._draw_rec_dot(False)

    def _draw_rec_dot(self, recording):
        self.rec_dot.delete("all")
        color = REC_RED if recording else "#3a4750"
        self.rec_dot.create_oval(2, 2, 18, 18, fill=color, outline="")

    def _panel(self, title):
        outer = tk.Frame(self.root, bg=PANEL, highlightthickness=1,
                          highlightbackground=BORDER)
        outer.pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(
            outer, text=title, font=("Meiryo", 10, "bold"),
            bg=PANEL, fg=ACCENT, anchor="w",
        ).pack(fill="x", padx=10, pady=(8, 0))
        return outer

    def _hotkey_row(self, parent, guide_text, label_var, on_change, on_toggle_text_var):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", padx=10, pady=(4, 0))
        tk.Label(row, textvariable=label_var, font=("Consolas", 11, "bold"),
                 bg=PANEL, fg=ACCENT).pack(side="left")
        tk.Button(
            row, text="変更", font=("Meiryo", 8), bg=PANEL_DARK, fg=TEXT_MAIN,
            activebackground=ACCENT_DIM, activeforeground=TEXT_MAIN,
            bd=0, highlightthickness=1, highlightbackground=BORDER, padx=6,
            command=on_change,
        ).pack(side="left", padx=(6, 0))
        tk.Label(row, text=guide_text, font=("Meiryo", 8), bg=PANEL, fg=TEXT_DIM,
                 ).pack(side="left", padx=(10, 0))

    def _build_record_panel(self):
        panel = self._panel("画面録画(動画)")

        self.record_hotkey_var = tk.StringVar()
        self._hotkey_row(
            panel, "を押すたびに開始/停止", self.record_hotkey_var,
            lambda: self.start_hotkey_capture("record_hotkey"), None,
        )

        row = tk.Frame(panel, bg=PANEL)
        row.pack(fill="x", padx=10, pady=(6, 10))
        self.record_btn_var = tk.StringVar(value="● 録画を開始")
        self.record_btn = tk.Button(
            row, textvariable=self.record_btn_var, font=("Meiryo", 9, "bold"),
            bg=PANEL_DARK, fg=REC_RED, activebackground="#2a1414",
            activeforeground=REC_RED, bd=0, highlightthickness=1,
            highlightbackground=BORDER, padx=10, pady=4,
            command=self.toggle_recording,
        )
        self.record_btn.pack(side="left")
        tk.Label(
            row, text=f"{self.cfg.get('video_fps', 8)}fpsでmp4として保存されます",
            font=("Meiryo", 8), bg=PANEL, fg=TEXT_DIM,
        ).pack(side="left", padx=(10, 0))

    def _build_screenshot_panel(self):
        panel = self._panel("自動スクリーンショット")

        self.screenshot_hotkey_var = tk.StringVar()
        self._hotkey_row(
            panel, "を押すたびに自動保存を開始/停止", self.screenshot_hotkey_var,
            lambda: self.start_hotkey_capture("screenshot_hotkey"), None,
        )

        row1 = tk.Frame(panel, bg=PANEL)
        row1.pack(fill="x", padx=10, pady=(6, 0))
        self.shot_btn_var = tk.StringVar(value="◎ 自動保存を開始")
        self.shot_btn = tk.Button(
            row1, textvariable=self.shot_btn_var, font=("Meiryo", 9, "bold"),
            bg=PANEL_DARK, fg=ACCENT, activebackground="#0f2b36",
            activeforeground=ACCENT, bd=0, highlightthickness=1,
            highlightbackground=BORDER, padx=10, pady=4,
            command=self.toggle_screenshot,
        )
        self.shot_btn.pack(side="left")
        tk.Button(
            row1, text="今すぐ1枚", font=("Meiryo", 9), bg=PANEL_DARK,
            fg=TEXT_MAIN, activebackground=ACCENT_DIM, activeforeground=TEXT_MAIN,
            bd=0, highlightthickness=1, highlightbackground=BORDER, padx=10,
            command=self.take_single_screenshot,
        ).pack(side="left", padx=(8, 0))

        row2 = tk.Frame(panel, bg=PANEL)
        row2.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(row2, text="間隔:", font=("Meiryo", 9), bg=PANEL,
                  fg=TEXT_MAIN).pack(side="left")
        self.interval_label_var = tk.StringVar()
        tk.Label(row2, textvariable=self.interval_label_var,
                  font=("Meiryo", 9, "bold"), bg=PANEL, fg=ACCENT,
                  ).pack(side="left", padx=(4, 10))
        for sec in INTERVAL_PRESETS:
            tk.Button(
                row2, text=f"{sec}秒", font=("Meiryo", 8), bg=PANEL_DARK,
                fg=TEXT_MAIN, activebackground=ACCENT_DIM,
                activeforeground=TEXT_MAIN, bd=0, highlightthickness=1,
                highlightbackground=BORDER, padx=6,
                command=lambda s=sec: self.set_interval(s),
            ).pack(side="left", padx=2)

        row3 = tk.Frame(panel, bg=PANEL)
        row3.pack(fill="x", padx=10, pady=(6, 10))
        tk.Label(row3, text="カスタム(秒):", font=("Meiryo", 8), bg=PANEL,
                  fg=TEXT_DIM).pack(side="left")
        self.custom_interval_entry = tk.Entry(
            row3, width=6, font=("Consolas", 9), bg=PANEL_DARK, fg=TEXT_MAIN,
            insertbackground=TEXT_MAIN, bd=0, highlightthickness=1,
            highlightbackground=BORDER,
        )
        self.custom_interval_entry.pack(side="left", padx=(4, 4))
        tk.Button(
            row3, text="適用", font=("Meiryo", 8), bg=PANEL_DARK, fg=TEXT_MAIN,
            activebackground=ACCENT_DIM, activeforeground=TEXT_MAIN,
            bd=0, highlightthickness=1, highlightbackground=BORDER, padx=6,
            command=lambda: self.set_interval(self.custom_interval_entry.get()),
        ).pack(side="left")

    def _build_folder_panel(self):
        panel = self._panel("保存状況")

        row1 = tk.Frame(panel, bg=PANEL)
        row1.pack(fill="x", padx=10, pady=(4, 0))
        tk.Label(row1, text="スクショ枚数(このセッション):", font=("Meiryo", 9),
                  bg=PANEL, fg=TEXT_MAIN).pack(side="left")
        self.shot_count_var = tk.StringVar(value="0枚")
        tk.Label(row1, textvariable=self.shot_count_var, font=("Meiryo", 9, "bold"),
                  bg=PANEL, fg=ACCENT).pack(side="left", padx=(4, 0))

        row2 = tk.Frame(panel, bg=PANEL)
        row2.pack(fill="x", padx=10, pady=(2, 0))
        tk.Label(row2, text="直近保存:", font=("Meiryo", 8), bg=PANEL,
                  fg=TEXT_DIM).pack(side="left")
        self.last_shot_var = tk.StringVar(value="なし")
        tk.Label(row2, textvariable=self.last_shot_var, font=("Meiryo", 8),
                  bg=PANEL, fg=TEXT_DIM).pack(side="left", padx=(4, 0))

        row3 = tk.Frame(panel, bg=PANEL)
        row3.pack(fill="x", padx=10, pady=(6, 4))
        tk.Label(row3, text="保存先:", font=("Meiryo", 8), bg=PANEL,
                  fg=TEXT_DIM).pack(side="left")
        self.folder_var = tk.StringVar()
        tk.Label(row3, textvariable=self.folder_var, font=("Meiryo", 8),
                  bg=PANEL, fg=TEXT_MAIN, wraplength=340, justify="left",
                  ).pack(side="left", padx=(4, 0))

        row4 = tk.Frame(panel, bg=PANEL)
        row4.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(
            row4, text="フォルダを開く", font=("Meiryo", 8), bg=PANEL_DARK,
            fg=TEXT_MAIN, activebackground=ACCENT_DIM, activeforeground=TEXT_MAIN,
            bd=0, highlightthickness=1, highlightbackground=BORDER, padx=8,
            command=self.open_save_folder,
        ).pack(side="left")
        tk.Button(
            row4, text="保存先を変更", font=("Meiryo", 8), bg=PANEL_DARK,
            fg=TEXT_MAIN, activebackground=ACCENT_DIM, activeforeground=TEXT_MAIN,
            bd=0, highlightthickness=1, highlightbackground=BORDER, padx=8,
            command=self.change_save_root,
        ).pack(side="left", padx=(6, 0))

    def _build_status_bar(self):
        bar = tk.Frame(self.root, bg=PANEL_DARK)
        bar.pack(fill="x", padx=0, pady=(10, 0))
        self.status_var = tk.StringVar(value="")
        tk.Label(
            bar, textvariable=self.status_var, font=("Meiryo", 8), bg=PANEL_DARK,
            fg=TEXT_DIM, anchor="w", padx=10, pady=6,
        ).pack(fill="x")

    # ---------- 録画 ----------

    def toggle_recording(self):
        if self.recorder.active:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        folder = os.path.join(self._get_session_dir(), "動画")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, time.strftime("録画_%Y%m%d_%H%M%S.mp4"))
        self.recorder.start(path)
        self.record_btn_var.set("■ 録画を停止")
        self._update_folder_label()
        self.events.put(("status", f"録画を開始しました: {os.path.basename(path)}"))

    def _stop_recording(self):
        self.recorder.stop()
        self.record_btn_var.set("● 録画を開始")
        self._maybe_close_session()
        if self.recorder.last_error:
            self.events.put(("status", f"録画エラー: {self.recorder.last_error}"))
        else:
            self.events.put(("status", "録画を停止しました"))

    # ---------- スクリーンショット ----------

    def toggle_screenshot(self):
        if self.shot_timer.active:
            self._stop_screenshot()
        else:
            self._start_screenshot()

    def _start_screenshot(self):
        folder = os.path.join(self._get_session_dir(), "スクショ")
        os.makedirs(folder, exist_ok=True)
        interval = self.cfg.get("screenshot_interval_sec", 30)
        self.shot_timer.start(folder, interval)
        self.shot_btn_var.set("■ 自動保存を停止")
        self._update_folder_label()
        self.events.put(("status", f"{interval}秒ごとの自動スクショを開始しました"))

    def _stop_screenshot(self):
        self.shot_timer.stop()
        self.shot_btn_var.set("◎ 自動保存を開始")
        self._maybe_close_session()
        self.events.put(("status", "自動スクショを停止しました"))

    def take_single_screenshot(self):
        folder = os.path.join(self._get_session_dir(), "スクショ")
        os.makedirs(folder, exist_ok=True)

        def _run():
            try:
                with mss.MSS() as sct:
                    monitor = get_primary_monitor(sct)
                    path = save_screenshot(sct, monitor, folder)
                self.shot_timer.add_manual_shot(path)
                self.events.put(("status", f"1枚保存しました: {os.path.basename(path)}"))
            except Exception as e:
                self.events.put(("status", f"スクショ失敗: {e}"))
            finally:
                self.events.put(("maybe_close_session", None))

        threading.Thread(target=_run, daemon=True).start()

    def set_interval(self, seconds):
        try:
            seconds = int(str(seconds).strip())
        except (TypeError, ValueError):
            self.events.put(("status", "間隔は数字(秒)で入力してください"))
            return
        if seconds < 1:
            self.events.put(("status", "間隔は1秒以上にしてください"))
            return
        self.cfg["screenshot_interval_sec"] = seconds
        save_config(self.cfg)
        self._update_interval_label()
        self.events.put(("status", f"スクショ間隔を{seconds}秒にしました"))
        if self.shot_timer.active:
            # 動いている最中に変えた場合は、枚数はそのまま次の撮影から
            # 新しい間隔に切り替える
            folder = os.path.join(self._get_session_dir(), "スクショ")
            self.shot_timer.stop()
            self.shot_timer.start(folder, seconds, reset_count=False)

    def _update_interval_label(self):
        self.interval_label_var.set(f"{self.cfg.get('screenshot_interval_sec', 30)}秒ごと")

    # ---------- 保存先 ----------

    def open_save_folder(self):
        target = self.session_dir or self.save_root
        try:
            os.startfile(target)
        except Exception as e:
            self.events.put(("status", f"フォルダを開けませんでした: {e}"))

    def change_save_root(self):
        if self._session_active():
            self.events.put(("status", "録画・スクショ動作中は保存先を変更できません"))
            return
        chosen = filedialog.askdirectory(
            initialdir=self.save_root, title="保存先フォルダを選択",
        )
        if not chosen:
            return
        self.cfg["save_root"] = chosen
        save_config(self.cfg)
        self.save_root = chosen
        os.makedirs(self.save_root, exist_ok=True)
        self.session_dir = None
        self._update_folder_label()
        self.events.put(("status", "保存先フォルダを変更しました"))

    def _update_folder_label(self):
        target = self.session_dir or self.save_root
        self.folder_var.set(target)

    # ---------- ホットキー ----------

    def _register_hotkeys(self):
        try:
            keyboard.add_hotkey(
                self.cfg["record_hotkey"], self._make_hotkey_handler("record"),
            )
        except Exception as e:
            self.events.put(("status", f"録画ホットキー登録失敗: {e}"))
        try:
            keyboard.add_hotkey(
                self.cfg["screenshot_hotkey"], self._make_hotkey_handler("screenshot"),
            )
        except Exception as e:
            self.events.put(("status", f"スクショホットキー登録失敗: {e}"))

    def _make_hotkey_handler(self, kind):
        def _handler():
            now = time.time()
            if now - self._last_toggle_time < 0.4:
                return
            self._last_toggle_time = now
            if kind == "record":
                self.toggle_recording()
            else:
                self.toggle_screenshot()
        return _handler

    def start_hotkey_capture(self, target):
        if self.waiting_hotkey_capture:
            return
        self.waiting_hotkey_capture = True
        self._capture_target = target
        label_var = (
            self.record_hotkey_var if target == "record_hotkey"
            else self.screenshot_hotkey_var
        )
        label_var.set("キー待機中…")

        def _capture():
            try:
                new_key = keyboard.read_hotkey(suppress=False)
            except Exception:
                new_key = None
            self.waiting_hotkey_capture = False
            if new_key:
                self.events.put(("hotkey_captured", new_key))
            else:
                self.events.put(("refresh_hotkeys", None))
        threading.Thread(target=_capture, daemon=True).start()

    def _refresh_hotkey_labels(self):
        self.record_hotkey_var.set(self.cfg["record_hotkey"].upper())
        self.screenshot_hotkey_var.set(self.cfg["screenshot_hotkey"].upper())

    def _apply_new_hotkey(self, new_key):
        target = self._capture_target
        other = "screenshot_hotkey" if target == "record_hotkey" else "record_hotkey"
        if new_key == self.cfg.get(other):
            self.events.put(("status", f"{new_key.upper()}はもう一方で使用中です"))
            self._refresh_hotkey_labels()
            return
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        self.cfg[target] = new_key
        save_config(self.cfg)
        self._register_hotkeys()
        self._refresh_hotkey_labels()
        self.events.put(("status", "ホットキーを変更しました"))

    # ---------- メインループ ----------

    def _poll(self):
        if self.recorder.active:
            secs = int(self.recorder.elapsed())
            self.rec_text_var.set("REC 録画中")
            self.rec_timer_var.set(
                f"{secs // 3600:02d}:{(secs % 3600) // 60:02d}:{secs % 60:02d}"
            )
            self._draw_rec_dot(True)
        else:
            self.rec_text_var.set("待機中")
            self.rec_timer_var.set("")
            self._draw_rec_dot(False)

        self.shot_count_var.set(f"{self.shot_timer.count}枚")
        if self.shot_timer.last_path:
            self.last_shot_var.set(os.path.basename(self.shot_timer.last_path))

        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "status":
                self.status_var.set(payload)
            elif kind == "hotkey_captured":
                self._apply_new_hotkey(payload)
            elif kind == "refresh_hotkeys":
                self._refresh_hotkey_labels()
            elif kind == "maybe_close_session":
                self._maybe_close_session()

        self.root.after(200, self._poll)

    def _on_close(self):
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        if self.recorder.active:
            self.recorder.stop()
        if self.shot_timer.active:
            self.shot_timer.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
