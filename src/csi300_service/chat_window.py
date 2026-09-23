"""A persistent, streaming chat workspace for the desktop application."""
from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from uuid import uuid4

from .ai_chat import analysis_system_prompt, build_analysis_context, free_chat_system_prompt
from .chat_client import ChatCancellation, ChatCancelled, ChatResult, StreamingChatClient
from .chat_store import ChatSession, ChatSettings, ChatStore, request_history


class ChatWindow:
    def __init__(self, app, colors: dict[str, str], store: ChatStore | None = None):
        self.app, self.colors = app, colors
        self.store = store or ChatStore()
        self.sessions = {session.id: session for session in self.store.load_all()}
        self.settings = self.store.load_settings()
        self.keys: dict[tuple[str, str], str] = {}
        self.runs: dict[str, dict] = {}
        self.current_id: str | None = None
        self.loading_context = False
        self.closed = False
        self.save_timer = None
        self.window = tk.Toplevel(app.root)
        self.window.title("AI 自由聊天 · Marketor")
        self.window.configure(bg=colors["bg"])
        width = min(1120, int(self.window.winfo_screenwidth() * .90))
        height = min(820, int(self.window.winfo_screenheight() * .88))
        self.window.geometry(f"{width}x{height}")
        self.window.minsize(min(760, width), min(580, height))
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Destroy>", self._destroyed, add="+")
        self.window.bind("<Control-n>", lambda event: self._new_shortcut())
        self.window.bind("<Escape>", lambda event: self.stop())
        self.status = tk.StringVar(value="Ctrl+Enter 发送 · Enter 换行 · 历史保存在本机")
        self._build()
        if self.sessions:
            active = self.store.active_id()
            self._switch(active if active in self.sessions else next(iter(self.sessions)))
        else:
            self.new_chat()
        if self.store.warnings:
            self.status.set("；".join(self.store.warnings))

    @property
    def session(self) -> ChatSession:
        return self.sessions[self.current_id]

    def _button(self, parent, text, command, *, primary=False, **kwargs):
        return tk.Button(parent, text=text, command=command, relief="flat", bd=0,
                         bg=self.colors["mint"] if primary else self.colors["button"],
                         fg=self.colors["bg"] if primary else self.colors["text"],
                         activebackground=self.colors["selected"], activeforeground=self.colors["text"],
                         padx=10, pady=7, cursor="hand2", font=("Microsoft YaHei UI", 9), **kwargs)

    def _label(self, parent, text="", **kwargs):
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=self.colors["text"],
                        font=("Microsoft YaHei UI", 10), **kwargs)

    def _build(self) -> None:
        sidebar = tk.Frame(self.window, bg=self.colors["panel"], width=196, padx=12, pady=14)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self._label(sidebar, "对话", anchor="w").pack(fill="x", pady=(0, 10))
        self._button(sidebar, "+  新对话", self.new_chat, primary=True).pack(fill="x")
        self.search = tk.StringVar()
        search = tk.Entry(sidebar, textvariable=self.search, bg=self.colors["panel_alt"], fg=self.colors["text"],
                          insertbackground=self.colors["text"], relief="flat", width=15)
        search.pack(fill="x", pady=(12, 3), ipady=7)
        self._label(sidebar, "搜索标题或消息", anchor="w").pack(fill="x", pady=(0, 6))
        self.search.trace_add("write", lambda *_: self._refresh_sessions())
        bottom = tk.Frame(sidebar, bg=self.colors["panel"])
        bottom.pack(side="bottom", fill="x", pady=(10, 0))
        self._button(bottom, "重命名", self.rename).pack(fill="x", pady=3)
        self._button(bottom, "导出 Markdown", self.export).pack(fill="x", pady=3)
        self._button(bottom, "删除当前对话", self.delete).pack(fill="x", pady=3)
        listing = tk.Frame(sidebar, bg=self.colors["panel"])
        listing.pack(fill="both", expand=True)
        self.session_list = ttk.Treeview(listing, show="tree", selectmode="browse", height=8)
        self.session_list.column("#0", width=148, minwidth=60)
        scroll = ttk.Scrollbar(listing, orient="vertical", command=self.session_list.yview)
        scroll.pack(side="right", fill="y")
        self.session_list.configure(yscrollcommand=scroll.set)
        self.session_list.pack(side="left", fill="both", expand=True)
        self.session_list.bind("<<TreeviewSelect>>", self._select_session)

        main = tk.Frame(self.window, bg=self.colors["bg"], padx=16, pady=14)
        main.pack(side="left", fill="both", expand=True)
        header = tk.Frame(main, bg=self.colors["bg"])
        header.pack(fill="x", pady=(0, 8))
        self._button(header, "模型设置", self.open_settings).pack(side="right")
        self.title = self._label(header, "新对话", anchor="w")
        self.title.pack(side="left", fill="x", expand=True)
        self.model_label = self._label(main, anchor="w")
        self.model_label.pack(fill="x")
        mode_row = tk.Frame(main, bg=self.colors["bg"])
        mode_row.pack(fill="x", pady=(5, 9))
        self.market_button = self._button(mode_row, "新建行情分析", self.new_market_chat)
        self.market_button.pack(side="right")
        self.mode_label = self._label(mode_row, "自由聊天", anchor="w", justify="left", wraplength=320)
        self.mode_label.pack(side="left", fill="x", expand=True)

        composer = tk.Frame(main, bg=self.colors["panel"], padx=12, pady=10)
        composer.pack(side="bottom", fill="x", pady=(10, 0))
        self.input = tk.Text(composer, height=4, wrap="word", undo=True, relief="flat", bd=0,
                             font=("Microsoft YaHei UI", 11), padx=8, pady=8,
                             bg=self.colors["panel_alt"], fg=self.colors["text"], insertbackground=self.colors["text"])
        self.input.pack(fill="x")
        self.input.bind("<Control-Return>", lambda event: self._send_shortcut())
        self.input.bind("<<Modified>>", self._draft_changed)
        controls = tk.Frame(composer, bg=self.colors["panel"])
        controls.pack(fill="x", pady=(8, 0))
        self.send_button = self._button(controls, "发送", self.send, primary=True)
        self.send_button.pack(side="right")
        self.stop_button = self._button(controls, "停止生成", self.stop, state="disabled")
        self.stop_button.pack(side="right", padx=6)
        status_label = self._label(controls, textvariable=self.status, justify="left", anchor="w", wraplength=320)
        status_label.pack(side="left", fill="x", expand=True)
        controls.bind("<Configure>", lambda e: status_label.configure(wraplength=max(120, e.width - 190)))

        actions = tk.Frame(main, bg=self.colors["bg"])
        actions.pack(side="bottom", fill="x", pady=(6, 0))
        self.regenerate_button = self._button(actions, "重新生成", self.regenerate)
        self.regenerate_button.pack(side="left")
        self._button(actions, "编辑上个问题", self.edit_question).pack(side="left", padx=6)
        self._button(actions, "复制回答", self.copy_answer).pack(side="left")
        self._button(actions, "回到底部", lambda: self.transcript.see("end")).pack(side="right")
        transcript_frame = tk.Frame(main, bg=self.colors["panel"])
        transcript_frame.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(transcript_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        self.transcript = tk.Text(transcript_frame, wrap="word", state="disabled", relief="flat", bd=0,
                                  bg=self.colors["panel"], fg=self.colors["text"], selectbackground=self.colors["selected"],
                                  font=("Microsoft YaHei UI", 11), padx=20, pady=16, spacing1=3, spacing3=8,
                                  yscrollcommand=scrollbar.set)
        self.transcript.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.transcript.yview)
        for tag, options in {
            "user": {"foreground": self.colors["mint"], "font": ("Microsoft YaHei UI", 10, "bold"), "spacing1": 18},
            "assistant": {"foreground": self.colors["cyan"], "font": ("Microsoft YaHei UI", 10, "bold"), "spacing1": 18},
            "heading": {"font": ("Microsoft YaHei UI", 14, "bold"), "spacing1": 10},
            "bold": {"font": ("Microsoft YaHei UI", 11, "bold")},
            "code": {"font": ("Consolas", 11), "background": self.colors["panel_alt"], "lmargin1": 12, "lmargin2": 12},
            "muted": {"foreground": self.colors["muted"], "font": ("Microsoft YaHei UI", 9)},
            "error": {"foreground": self.colors["coral"]},
        }.items():
            self.transcript.tag_configure(tag, **options)

    def _save(self, session: ChatSession) -> bool:
        try:
            self.store.save(session)
            return True
        except (OSError, ValueError) as exc:
            self.status.set(f"本地保存失败，内容暂留内存：{exc}")
            return False

    def _remember_draft(self) -> None:
        if self.current_id:
            draft = self.input.get("1.0", "end-1c")
            self.session.draft = draft
            self._save(self.session)

    def _draft_changed(self, _event=None) -> None:
        if self.input.edit_modified():
            self.input.edit_modified(False)
            if self.current_id:
                self.session.draft = self.input.get("1.0", "end-1c")
            if self.save_timer:
                self.window.after_cancel(self.save_timer)
            self.save_timer = self.window.after(600, self._save_draft)

    def _save_draft(self) -> None:
        self.save_timer = None
        self._remember_draft()

    def _refresh_sessions(self) -> None:
        query = self.search.get().strip().lower()
        self.session_list.delete(*self.session_list.get_children())
        for session in sorted(self.sessions.values(), key=lambda item: item.updated_at, reverse=True):
            if query and query not in session.title.lower() and not any(query in msg["content"].lower() for msg in session.messages):
                continue
            self.session_list.insert("", "end", iid=session.id, text=("● " if session.id in self.runs else "") + session.title)
        if self.current_id and self.session_list.exists(self.current_id):
            self.session_list.selection_set(self.current_id)

    def _select_session(self, _event=None) -> None:
        selected = self.session_list.selection()
        if selected and selected[0] != self.current_id:
            self._switch(selected[0])

    def _switch(self, session_id: str) -> None:
        self._remember_draft()
        self.current_id = session_id
        self.input.delete("1.0", "end")
        self.input.insert("1.0", self.session.draft)
        self.input.edit_modified(False)
        self._refresh_sessions()
        self._render()
        try:
            self.store.set_active(session_id)
        except OSError as exc:
            self.status.set(f"无法保存当前会话位置：{exc}")
        self.input.focus_set()

    def _new_shortcut(self) -> str:
        self.new_chat()
        return "break"

    def new_chat(self) -> None:
        self._remember_draft()
        session = ChatSession()
        self.sessions[session.id] = session
        self._save(session)
        self._switch(session.id)

    def new_market_chat(self) -> None:
        if self.loading_context:
            return
        self.loading_context = True
        self.market_button.configure(state="disabled")
        symbol = self.app.current_symbol
        self.status.set("正在准备行情摘要，自由聊天仍可使用…")
        def work():
            try:
                context = build_analysis_context(symbol, catalog=self.app.catalog)
                self.app._post_ui(self._market_ready, context, None, owner=self.window)
            except Exception as exc:
                self.app._post_ui(self._market_ready, None, str(exc), owner=self.window)
        threading.Thread(target=work, daemon=True).start()

    def _market_ready(self, context, error) -> None:
        self.loading_context = False
        self.market_button.configure(state="normal")
        if error:
            self.status.set(f"行情摘要不可用：{error}")
            return
        session = ChatSession(title=f"行情 · {context['instrument']['name']}", context=context)
        self.sessions[session.id] = session
        self._save(session)
        self._switch(session.id)

    def _insert_markdown(self, content: str) -> None:
        code = False
        for line in content.splitlines():
            if line.strip().startswith("```"):
                code = not code
                if code:
                    self.transcript.insert("end", (line.strip()[3:] or "代码") + "\n", "muted")
                continue
            if code or line.startswith("|"):
                self.transcript.insert("end", line + "\n", "code")
            elif re.match(r"^#{1,6} ", line):
                self.transcript.insert("end", re.sub(r"^#{1,6} ", "", line) + "\n", "heading")
            else:
                line = re.sub(r"^\s*[-*] ", "• ", line)
                for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", line):
                    if part.startswith("**") and part.endswith("**"):
                        self.transcript.insert("end", part[2:-2], "bold")
                    elif part.startswith("`") and part.endswith("`"):
                        self.transcript.insert("end", part[1:-1], "code")
                    else:
                        self.transcript.insert("end", part)
                self.transcript.insert("end", "\n")

    def _render(self, *, preserve_scroll=False) -> None:
        scroll = self.transcript.yview()
        session = self.session
        self.title.configure(text=session.title[:36])
        self.model_label.configure(text=f"{self.settings.provider}  /  {self.settings.model}")
        self.mode_label.configure(text=(f"行情摘要 · {session.context['instrument']['name']}\n截至 {session.context['context_policy']['data_cutoff']}" if session.context else "自由聊天 · 不附带本地行情"))
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        if not session.messages:
            self.transcript.insert("end", "从一个问题开始\n\n", "heading")
            self.transcript.insert("end", "可以一起写作、学习、分析问题或修改代码。\n\n")
            self.transcript.insert("end", "试试：\n• 帮我把这段文字改得简洁自然\n• 用例子解释一个我不理解的概念\n• 一步步分析这段代码的问题\n\n", "muted")
            self.transcript.insert("end", "回复会逐步显示，支持停止生成。\n历史保存在本机；发送时只附带当前会话的近期上下文。", "muted")
        for index, message in enumerate(session.messages):
            is_user = message["role"] == "user"
            label = "你" if is_user else f"Marketor AI · {message.get('model', 'AI')}"
            self.transcript.insert("end", label + "\n", "user" if is_user else "assistant")
            if is_user or message.get("status") == "pending":
                self.transcript.insert("end", message["content"])
            else:
                self._insert_markdown(message["content"])
            if message.get("status") == "pending":
                self.transcript.mark_set("stream_end", "end-1c")
                self.transcript.mark_gravity("stream_end", "left")
            self.transcript.insert("end", "\n\n")
            if message.get("error"):
                self.transcript.insert("end", message["error"] + "\n", "error")
            elif message.get("status") == "stopped":
                self.transcript.insert("end", "已停止，以上为部分回复\n", "muted")
            if message.get("finish_reason") == "length":
                self.transcript.insert("end", "已达到回复长度上限，可发送“继续”或在模型设置中提高长度。\n", "muted")
        self.transcript.configure(state="disabled")
        if preserve_scroll and scroll[1] < .98:
            self.transcript.yview_moveto(scroll[0])
        else:
            self.transcript.see("end")
        self._controls()

    def _controls(self) -> None:
        running = self.current_id in self.runs
        self.send_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")
        self.regenerate_button.configure(state="normal" if not running and any(m["role"] == "user" for m in self.session.messages) else "disabled")
        if running:
            self.status.set(self.runs[self.current_id].get("phase", "正在连接模型…"))
        else:
            self.status.set("Ctrl+Enter 发送 · Enter 换行 · 本地自动保存")

    def _send_shortcut(self) -> str:
        self.send()
        return "break"

    def send(self) -> None:
        question = self.input.get("1.0", "end-1c").strip()
        if not question or self.current_id in self.runs:
            return
        if len(question) > 32000:
            self.status.set("单次问题请控制在 32,000 字符以内")
            return
        self._start(question)

    def regenerate(self) -> None:
        if self.current_id in self.runs:
            return
        question = next((m["content"] for m in reversed(self.session.messages) if m["role"] == "user"), None)
        if question:
            self._start(question, regenerate=True)

    def _start(self, question: str, *, regenerate=False) -> None:
        if len(self.runs) >= 3:
            self.status.set("已有 3 个会话生成中，请先停止一个或等待完成")
            return
        settings = replace(self.settings)
        key = self.keys.get((settings.provider, settings.base_url)) or os.getenv(settings.key_env, "").strip()
        if not key:
            self.status.set("先在模型设置中填写 API Key，再开始聊天")
            self.open_settings()
            return
        session = self.session
        source = session.messages if regenerate else [*session.messages, {"role": "user", "content": question}]
        try:
            settings.validate()
            messages, omitted = request_history(source, settings.context_chars)
        except ValueError as exc:
            self.status.set(str(exc))
            return
        if not regenerate:
            session.add("user", question)
            session.draft = ""
            self.input.delete("1.0", "end")
        message = session.add("assistant", "", status="pending", model=settings.model)
        token = uuid4().hex
        cancellation = ChatCancellation()
        self.runs[session.id] = {"token": token, "cancellation": cancellation, "message": message,
                                 "saved": time.monotonic(), "phase": "正在连接模型…", "omitted": omitted}
        if not self._save(session):
            # Keep working in memory; the save error remains visible on completion.
            pass
        self._refresh_sessions()
        self._render()
        system = analysis_system_prompt(session.context) if session.context else free_chat_system_prompt()
        if settings.system_prompt.strip():
            system += "\n\n用户自定义回答偏好：\n" + settings.system_prompt.strip()
        client = StreamingChatClient(api_key=key, base_url=settings.base_url, model=settings.model)
        def work():
            pending: list[str] = []
            last = time.monotonic()
            def flush():
                nonlocal last
                if pending:
                    self.app._post_ui(self._chunk, session.id, token, "".join(pending), owner=self.window)
                    pending.clear()
                last = time.monotonic()
            def on_token(text):
                pending.append(text)
                if time.monotonic() - last >= .04:
                    flush()
            try:
                result = client.stream_chat(system, messages, on_token=on_token, cancellation=cancellation,
                                            temperature=settings.temperature, max_tokens=settings.max_tokens,
                                            on_thinking=lambda: self.app._post_ui(self._phase, session.id, token, "模型正在思考…", owner=self.window))
                flush()
                self.app._post_ui(self._finished, session.id, token, result, None, owner=self.window)
            except ChatCancelled:
                pass
            except Exception as exc:
                flush()
                self.app._post_ui(self._finished, session.id, token, None, str(exc), owner=self.window)
        threading.Thread(target=work, daemon=True).start()

    def _phase(self, session_id, token, phase) -> None:
        run = self.runs.get(session_id)
        if run and run["token"] == token:
            run["phase"] = phase
            if session_id == self.current_id:
                self.status.set(phase)

    def _chunk(self, session_id, token, text) -> None:
        run = self.runs.get(session_id)
        if not run or run["token"] != token:
            return
        run["message"]["content"] += text
        run["phase"] = f"正在回复 · {len(run['message']['content']):,} 字符"
        if session_id == self.current_id:
            follow = self.transcript.yview()[1] >= .98
            self.transcript.configure(state="normal")
            self.transcript.mark_gravity("stream_end", "right")
            self.transcript.insert("stream_end", text)
            self.transcript.mark_gravity("stream_end", "left")
            self.transcript.configure(state="disabled")
            if follow:
                self.transcript.see("end")
            self.status.set(run["phase"])
        if time.monotonic() - run["saved"] > 2:
            self._save(self.sessions[session_id])
            run["saved"] = time.monotonic()

    def _finished(self, session_id, token, result: ChatResult | None, error: str | None) -> None:
        run = self.runs.get(session_id)
        if not run or run["token"] != token:
            return
        self.runs.pop(session_id)
        message = run["message"]
        message["status"] = "error" if error else "complete"
        if result:
            message.update(content=result.text, finish_reason=result.finish_reason, usage=result.usage)
        if error:
            message["error"] = error + "；可点击重新生成，原问题和部分回复已保留"
        self._refresh_sessions()
        if session_id == self.current_id:
            self._render(preserve_scroll=True)
            if error:
                self.status.set("本次回复失败，可重新生成")
            elif run["omitted"]:
                self.status.set(f"回复完成 · 较早的 {run['omitted']} 轮未发送，完整历史仍保留在本机")
        self._save(self.sessions[session_id])

    def stop(self, session_id=None) -> None:
        session_id = session_id or self.current_id
        run = self.runs.pop(session_id, None)
        if not run:
            return
        run["cancellation"].cancel()
        run["message"]["status"] = "stopped"
        if not self.closed:
            self._refresh_sessions()
            if session_id == self.current_id:
                self._render(preserve_scroll=True)
                self.status.set("已停止接收，部分回复已保留")
        self._save(self.sessions[session_id])

    def edit_question(self) -> None:
        question = next((m["content"] for m in reversed(self.session.messages) if m["role"] == "user"), None)
        if question:
            if self.input.get("1.0", "end-1c").strip() and not messagebox.askyesno("替换输入草稿", "用上个问题替换当前草稿？", parent=self.window):
                return
            self.input.delete("1.0", "end")
            self.input.insert("1.0", question)
            self.input.focus_set()
            self.status.set("修改后发送会作为新消息，原问题和回答保留")

    def copy_answer(self) -> None:
        answer = next((m["content"] for m in reversed(self.session.messages) if m["role"] == "assistant" and m["content"]), None)
        if answer:
            self.window.clipboard_clear()
            self.window.clipboard_append(answer)
            self.status.set("已复制最后一条回复（Markdown 原文）")

    def rename(self) -> None:
        title = simpledialog.askstring("重命名对话", "对话名称", initialvalue=self.session.title, parent=self.window)
        if title and title.strip():
            self.session.title = title.strip()[:100]
            self._save(self.session)
            self._refresh_sessions()
            self.title.configure(text=self.session.title[:36])

    def export(self) -> None:
        path = filedialog.asksaveasfilename(parent=self.window, defaultextension=".md", initialfile="Marketor-对话.md", filetypes=[("Markdown", "*.md")])
        if path:
            try:
                Path(path).write_text(self.session.export_markdown(), encoding="utf-8")
                self.status.set("对话已导出")
            except OSError as exc:
                self.status.set(f"导出失败：{exc}")

    def delete(self) -> None:
        if not messagebox.askyesno("删除当前对话", f"删除“{self.session.title}”及其本地消息？", parent=self.window):
            return
        self.stop()
        try:
            self.store.delete(self.current_id)
        except OSError as exc:
            self.status.set(f"删除失败：{exc}")
            return
        self.sessions.pop(self.current_id)
        self.current_id = None
        if self.sessions:
            self._switch(next(iter(self.sessions)))
        else:
            self.new_chat()

    def _destroyed(self, event) -> None:
        if event.widget is self.window and not self.closed:
            self._shutdown()

    def _shutdown(self) -> None:
        try:
            self._remember_draft()
        except tk.TclError:
            if self.current_id:
                self._save(self.session)
        self.closed = True
        if self.save_timer:
            try:
                self.window.after_cancel(self.save_timer)
            except tk.TclError:
                pass
        for session_id in list(self.runs):
            self.stop(session_id)
        self.keys.clear()

    def close(self) -> None:
        self._shutdown()
        self.window.destroy()

    def open_settings(self) -> None:
        existing = getattr(self, "settings_window", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        window = self.settings_window = tk.Toplevel(self.window)
        window.title("聊天模型设置")
        window.configure(bg=self.colors["panel"])
        window.transient(self.window)
        window.geometry("600x630")
        window.minsize(520, 600)
        panel = tk.Frame(window, bg=self.colors["panel"], padx=20, pady=16)
        panel.pack(fill="both", expand=True)
        panel.columnconfigure(1, weight=1)
        provider = tk.StringVar(value=self.settings.provider)
        base = tk.StringVar(value=self.settings.base_url)
        model = tk.StringVar(value=self.settings.model)
        key = tk.StringVar()
        temperature = tk.StringVar(value=str(self.settings.temperature))
        max_tokens = tk.StringVar(value=str(self.settings.max_tokens))
        context = tk.StringVar(value=str(self.settings.context_chars))
        info = tk.StringVar(value="API Key 留空则沿用内存或环境变量中的密钥。")
        remember = tk.BooleanVar(value=False)
        for row, label in enumerate(("服务", "Base URL", "模型", "API Key", "创造性（0–2）", "回复长度（tokens）", "上下文预算（字符）")):
            self._label(panel, label, anchor="w").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
        provider_box = ttk.Combobox(panel, textvariable=provider, values=["DeepSeek", "OpenAI 兼容接口"], state="readonly")
        provider_box.grid(row=0, column=1, sticky="ew", pady=5)
        model_box = ttk.Combobox(panel, textvariable=model)
        model_box.grid(row=2, column=1, sticky="ew", pady=5)
        for row, variable in ((1, base), (3, key), (4, temperature), (5, max_tokens), (6, context)):
            tk.Entry(panel, textvariable=variable, show="●" if row == 3 else "", bg=self.colors["panel_alt"], fg=self.colors["text"],
                     insertbackground=self.colors["text"], relief="flat").grid(row=row, column=1, sticky="ew", pady=5, ipady=6)
        def provider_changed(_event=None):
            base.set("https://api.deepseek.com" if provider.get() == "DeepSeek" else "https://api.openai.com/v1")
            model.set("deepseek-v4-flash" if provider.get() == "DeepSeek" else "")
            key.set("")
        provider_box.bind("<<ComboboxSelected>>", provider_changed)
        tk.Checkbutton(panel, text="记住密钥（当前 Windows 用户环境变量）", variable=remember, bg=self.colors["panel"], fg=self.colors["text"], selectcolor=self.colors["panel_alt"]).grid(row=7, column=0, columnspan=2, sticky="w", pady=5)
        self._label(panel, "回答偏好 / 自定义指令", anchor="w").grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 4))
        prompt = tk.Text(panel, height=4, wrap="word", bg=self.colors["panel_alt"], fg=self.colors["text"], insertbackground=self.colors["text"], relief="flat")
        prompt.insert("1.0", self.settings.system_prompt)
        prompt.grid(row=9, column=0, columnspan=2, sticky="nsew")
        panel.rowconfigure(9, weight=1)
        self._label(panel, textvariable=info, wraplength=530, justify="left", anchor="w").grid(row=10, column=0, columnspan=2, sticky="ew", pady=10)
        actions = tk.Frame(panel, bg=self.colors["panel"])
        actions.grid(row=11, column=0, columnspan=2, sticky="ew")
        def candidate(check_model=True):
            settings = ChatSettings(provider.get(), base.get(), model.get() or ("model-list" if not check_model else ""),
                                    float(temperature.get()), int(max_tokens.get()), int(context.get()), prompt.get("1.0", "end-1c"))
            settings.validate()
            return settings
        def fetch_models():
            try:
                settings = candidate(False)
                secret = key.get().strip() or self.keys.get((settings.provider, settings.base_url)) or os.getenv(settings.key_env, "")
                if not secret:
                    raise ValueError("请先填写 API Key")
            except ValueError as exc:
                info.set(str(exc))
                return
            models_button.configure(state="disabled")
            info.set("正在获取模型列表…")
            def finish(values, error):
                models_button.configure(state="normal")
                if error:
                    info.set(f"无法获取模型列表：{error}；也可直接填写模型名称")
                else:
                    model_box.configure(values=values)
                    info.set(f"连接成功，获取 {len(values)} 个模型。请在模型下拉框选择。")
            def work():
                try:
                    values = StreamingChatClient(api_key=secret, base_url=settings.base_url, model=settings.model).list_models()
                    self.app._post_ui(finish, values, None, owner=window)
                except Exception as exc:
                    self.app._post_ui(finish, [], str(exc), owner=window)
            threading.Thread(target=work, daemon=True).start()
        def save():
            try:
                settings = candidate()
                secret = key.get().strip()
                if secret and remember.get():
                    from .desktop import save_user_api_key
                    save_user_api_key(settings.key_env, secret)
                self.store.save_settings(settings)
                if secret:
                    self.keys[(settings.provider, settings.base_url)] = secret
                self.settings = settings
            except (ValueError, OSError) as exc:
                info.set(f"设置未保存：{exc}")
                return
            self.model_label.configure(text=f"{settings.provider}  /  {settings.model}")
            window.destroy()
            self.status.set("模型设置已保存，下次请求生效")
        models_button = self._button(actions, "获取模型列表", fetch_models)
        models_button.pack(side="left")
        self._button(actions, "保存设置", save, primary=True).pack(side="right")
        self._button(actions, "取消", window.destroy).pack(side="right", padx=8)
