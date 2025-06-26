from __future__ import annotations
import random
import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog, scrolledtext
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import uuid
import time
import json
import hashlib
from typing import Any, Optional
from multiprocessing import Process, Queue, Manager
import queue
import platform

try:
    from address_utils import generate_mnemonic, address_from_mnemonic
except ModuleNotFoundError:
    print("Warning: address_utils not found, using dummy functions for testing.")
    def generate_mnemonic(num_words: int = 24) -> str:
        return " ".join(['test'] * num_words)
    def address_from_mnemonic(mnemonic: str) -> str:
        return "0x" + "a" * 40

try:
    from node import Node
except ModuleNotFoundError:
    print("ERROR: node.py not found. GUI Miner functionality will fail.")
    Node = None

POW_DIFF = 5
TXS_PER_BLOCK = 8

def json_pretty(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, default=str)

def latest_genome_tx(chain, addr: str):
    chain_snapshot = list(chain)
    for blk in reversed(chain_snapshot):
        transactions = blk.get("transactions", [])
        for tx in transactions:
            if tx.get("type") == "upload_genome" and tx.get("user") == addr:
                return tx
    return None

def has_consent(chain, addr: str, trait: str) -> bool:
    chain_snapshot = list(chain)
    for blk in reversed(chain_snapshot):
        transactions = blk.get("transactions", [])
        for tx in transactions:
            if (
                tx.get("type") == "consent"
                and tx.get("user") == addr
                and tx.get("trait") == trait
            ):
                return True
    return False

class BlockExplorer(ttk.Window):
    def __init__(self, chain, mempool, balances, log_queue: Queue, refresh_ms=1000, theme='cyborg'):
        super().__init__(themename=theme, title="46-and-Me Blockchain Explorer")
        self.geometry("1150x760")

        self.chain = chain
        self.mempool = mempool
        self.balances = balances
        self.log_queue = log_queue
        self.refresh_ms = refresh_ms
        self.current_mnemonic: str | None = None
        self.current_address: str | None = None
        self.last_processed_block_index = -1
        self.last_displayed_block_index = -1
        self.gui_miner_process: Optional[Process] = None
        self.mining_status_var = tk.StringVar(value="Idle")
        self.os_platform = platform.system()

        nb = ttk.Notebook(self, bootstyle="dark")
        nb.pack(fill=tk.BOTH, expand=TRUE, padx=10, pady=10)

        self._tab_blocks(nb)
        self._tab_console(nb)
        self._tab_search(nb)

        self.after(200, self.refresh)
        self.after(500, self._check_log_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_mousewheel(self, event, widget):
        if self.os_platform == "Linux":
            if event.num == 4:
                widget.yview_scroll(-1, "units")
            elif event.num == 5:
                widget.yview_scroll(1, "units")
        elif self.os_platform == "Windows":
            widget.yview_scroll(int(-1 * (event.delta / 120)), "units")
        else:
             widget.yview_scroll(-1 * event.delta, "units")

    def _bind_mouse_scroll(self, widget_to_bind, scroll_target_widget=None):
        if scroll_target_widget is None:
            scroll_target_widget = widget_to_bind

        widget_to_bind.bind(
            "<MouseWheel>",
            lambda event, w=scroll_target_widget: self._on_mousewheel(event, w),
            add='+'
        )
        widget_to_bind.bind(
            "<Button-4>",
            lambda event, w=scroll_target_widget: self._on_mousewheel(event, w),
            add='+'
        )
        widget_to_bind.bind(
            "<Button-5>",
            lambda event, w=scroll_target_widget: self._on_mousewheel(event, w),
            add='+'
        )
        for child_widget in widget_to_bind.winfo_children():
             if not isinstance(child_widget, ttk.Scrollbar):
                  self._bind_mouse_scroll(child_widget, scroll_target_widget)

    def _on_close(self):
        if self.gui_miner_process and self.gui_miner_process.is_alive():
            print("[GUI] Terminating active GUI miner process...")
            self.gui_miner_process.terminate()
            self.gui_miner_process.join(timeout=0.5)
        self.destroy()

    def _tab_blocks(self, nb):
        tab = ttk.Frame(nb, padding=(10, 10))
        nb.add(tab, text="⛓️ Blocks")

        pw = ttk.PanedWindow(tab, orient=HORIZONTAL)
        pw.pack(fill=BOTH, expand=TRUE)

        frame_blocks = ttk.Frame(pw, padding=5)
        ttk.Label(frame_blocks, text="Chain Blocks", font="-weight bold", bootstyle=PRIMARY).pack(pady=(0, 5))
        self.block_list_tv = ttk.Treeview(frame_blocks, columns=("block_info",), show="", selectmode="browse", bootstyle=PRIMARY)
        self.block_list_tv.column("#0", width=0, stretch=NO)
        self.block_list_tv.column("block_info", anchor=W)
        self.block_list_tv.pack(side=LEFT, fill=BOTH, expand=TRUE)
        block_scroll = ttk.Scrollbar(frame_blocks, orient=VERTICAL, command=self.block_list_tv.yview, bootstyle="round-primary")
        block_scroll.pack(side=RIGHT, fill=Y)
        self.block_list_tv.config(yscrollcommand=block_scroll.set)
        self.block_list_tv.bind("<<TreeviewSelect>>", self._show_block_treeview)
        self._bind_mouse_scroll(self.block_list_tv)
        pw.add(frame_blocks, weight=1)

        right_frame = ttk.Frame(pw, padding=5)
        right_frame.columnconfigure(0, weight=1)

        ttk.Label(right_frame, text="Block Details", font="-weight bold", bootstyle=SECONDARY).grid(row=0, column=0, sticky=EW, pady=(0, 5))
        self.detail_txt = scrolledtext.ScrolledText(right_frame, height=15, wrap=tk.NONE)
        self.detail_txt.grid(row=1, column=0, sticky=NSEW, pady=(0, 10))
        try:
             bg_color = self.style.colors.inputbg
             fg_color = self.style.colors.inputfg
             self.detail_txt.configure(bg=bg_color, fg=fg_color, insertbackground=fg_color)
        except Exception as e:
             pass
             # print(f"Could not style detail_txt: {e}") # Comment removed
        self.detail_txt.config(state=tk.DISABLED)
        self._bind_mouse_scroll(self.detail_txt)
        right_frame.rowconfigure(1, weight=3)

        self.mem_frame = ttk.LabelFrame(right_frame, text=" M Pending Transactions (Mempool) ", bootstyle=INFO)
        self.mem_frame.grid(row=2, column=0, sticky=NSEW, pady=(10, 0))
        self.mem_frame.columnconfigure(0, weight=1)
        self.mem_frame.rowconfigure(0, weight=1)
        self.mempool_tv = ttk.Treeview(self.mem_frame, columns=("tx_info",), show="", selectmode="none", bootstyle=INFO)
        self.mempool_tv.column("#0", width=0, stretch=NO)
        self.mempool_tv.column("tx_info", anchor=W)
        self.mempool_tv.grid(row=0, column=0, sticky=NSEW, padx=5, pady=5)
        mem_scroll = ttk.Scrollbar(self.mem_frame, orient=VERTICAL, command=self.mempool_tv.yview, bootstyle="round-info")
        mem_scroll.grid(row=0, column=1, sticky=NS, pady=5)
        self.mempool_tv.config(yscrollcommand=mem_scroll.set)
        self._bind_mouse_scroll(self.mempool_tv)
        right_frame.rowconfigure(2, weight=2)
        pw.add(right_frame, weight=3)

    def _tab_search(self, nb):
        tab = ttk.Frame(nb, padding=(10, 10))
        nb.add(tab, text="🔍 Search")
        pad = {"padx": 5, "pady": 5}
        tab.columnconfigure(0, weight=1)

        top = ttk.Frame(tab)
        top.grid(row=0, column=0, sticky=EW, pady=(0, 10))
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Address:", width=10).grid(row=0, column=0, sticky=W, **pad)
        self.search_entry = ttk.Entry(top, bootstyle=PRIMARY)
        self.search_entry.grid(row=0, column=1, sticky=EW, **pad)
        ttk.Button(top, text="Search", command=self._search_addr, bootstyle=(PRIMARY, OUTLINE)).grid(row=0, column=2, sticky=E, **pad)

        self.search_balance_var = tk.StringVar(value="Enter address to search...")
        search_balance_label = ttk.Label(tab, textvariable=self.search_balance_var, font="-weight bold", bootstyle=SECONDARY)
        search_balance_label.grid(row=1, column=0, sticky=W, **pad)

        cols = ("blk", "tx_id", "type", "trait", "time")
        self.tree = ttk.Treeview(tab, columns=cols, show="headings", height=18, bootstyle=PRIMARY)
        self.tree.heading("blk", text="Blk #", anchor=W)
        self.tree.column("blk", width=60, anchor=W)
        self.tree.heading("tx_id", text="Tx ID", anchor=W)
        self.tree.column("tx_id", width=120, anchor=W)
        self.tree.heading("type", text="Type", anchor=W)
        self.tree.column("type", width=120, anchor=W)
        self.tree.heading("trait", text="Trait/Detail", anchor=W)
        self.tree.column("trait", width=150, anchor=W)
        self.tree.heading("time", text="Timestamp", anchor=W)
        self.tree.column("time", width=180, anchor=W)
        try:
            self.tree.tag_configure('oddrow', background=self.style.colors.light)
            self.tree.tag_configure('evenrow', background=self.style.colors.inputbg)
        except Exception:
            pass
        self.tree.grid(row=2, column=0, sticky=NSEW, **pad)
        tab.rowconfigure(2, weight=1)

        tree_scroll_y = ttk.Scrollbar(tab, orient=VERTICAL, command=self.tree.yview, bootstyle="round-primary")
        tree_scroll_y.grid(row=2, column=1, sticky=NS, pady=pad['pady'])
        self.tree.configure(yscrollcommand=tree_scroll_y.set)
        tree_scroll_x = ttk.Scrollbar(tab, orient=HORIZONTAL, command=self.tree.xview, bootstyle="round-primary")
        tree_scroll_x.grid(row=3, column=0, sticky=EW, padx=pad['padx'])
        self.tree.configure(xscrollcommand=tree_scroll_x.set)
        self._bind_mouse_scroll(self.tree)

    def _tab_console(self, nb):
        tab = ttk.Frame(nb, padding=(10, 10))
        nb.add(tab, text="👤 Console")

        pw = ttk.PanedWindow(tab, orient=VERTICAL)
        pw.pack(fill=BOTH, expand=TRUE)

        actions_pane = ttk.Frame(pw, padding=5)
        actions_pane.columnconfigure(0, weight=1)

        wallet_frame = ttk.LabelFrame(actions_pane, text="🔑 Wallet Management", bootstyle=INFO)
        wallet_frame.grid(row=0, column=0, sticky=EW, pady=(0, 10))
        wallet_frame.columnconfigure(1, weight=1)
        ttk.Label(wallet_frame, text="Mnemonic Phrase:").grid(row=0, column=0, sticky=W, padx=5, pady=5)
        self.mnemonic_entry = ttk.Entry(wallet_frame, width=80, show='*')
        self.mnemonic_entry.grid(row=0, column=1, columnspan=2, sticky=EW, padx=5, pady=5)
        ttk.Button(wallet_frame, text="Restore Wallet", command=self._restore_wallet, bootstyle=SUCCESS).grid(row=1, column=1, sticky=EW, padx=5, pady=5)
        ttk.Button(wallet_frame, text="Create New Wallet", command=self._create_wallet, bootstyle=INFO).grid(row=1, column=2, sticky=EW, padx=5, pady=5)

        self.actions_frame = ttk.LabelFrame(actions_pane, text="⚡ Wallet Actions", bootstyle=PRIMARY)
        self.actions_frame.grid(row=1, column=0, sticky=EW, pady=(0, 10))
        info_frame = ttk.Frame(self.actions_frame)
        info_frame.pack(fill=X, padx=5, pady=5)
        ttk.Label(info_frame, text="Address:").pack(side=LEFT)
        self.logged_in_address_var = tk.StringVar(value="N/A")
        self.address_display_entry = ttk.Entry(info_frame, textvariable=self.logged_in_address_var, state="readonly", bootstyle=PRIMARY)
        self.address_display_entry.pack(side=LEFT, padx=(2, 2), fill=X, expand=TRUE)
        self.copy_addr_button = ttk.Button(info_frame, text="Copy", width=5, command=self._copy_address_to_clipboard, bootstyle=(SECONDARY, OUTLINE))
        self.copy_addr_button.pack(side=LEFT, padx=(0, 5))
        self.balance_var = tk.StringVar(value="0 GEN46")
        ttk.Label(info_frame, text="Balance:", bootstyle=SUCCESS).pack(side=LEFT, padx=(10, 2))
        ttk.Label(info_frame, textvariable=self.balance_var, bootstyle=SUCCESS).pack(side=LEFT)
        genome_frame = ttk.Frame(self.actions_frame)
        genome_frame.pack(fill=X, padx=5, pady=5)
        self.load_genome_btn = ttk.Button(genome_frame, text="Load My Traits", command=self._load_genome, bootstyle=INFO)
        self.load_genome_btn.pack(side=LEFT, padx=(0, 5))
        ttk.Label(genome_frame, text="Trait:").pack(side=LEFT, padx=(10, 5))
        self.trait_combo = ttk.Combobox(genome_frame, state="disabled", width=25, bootstyle=INFO)
        self.trait_combo.pack(side=LEFT, padx=(0, 5))
        self.consent_btn = ttk.Button(genome_frame, text="Consent Selected Trait", command=self._consent_trait, bootstyle=(SUCCESS, OUTLINE))
        self.consent_btn.pack(side=LEFT, padx=(0, 5))
        other_frame = ttk.Frame(self.actions_frame)
        other_frame.pack(fill=X, padx=5, pady=5)
        self.upload_genome_btn = ttk.Button(other_frame, text="Upload New Genome File", command=self._upload_genome, bootstyle=SECONDARY)
        self.upload_genome_btn.pack(side=LEFT, padx=(0, 5))
        self.request_access_btn = ttk.Button(other_frame, text="Request Access to Trait", command=self._request_access, bootstyle=WARNING)
        self.request_access_btn.pack(side=LEFT, padx=(0, 5))

        mining_frame = ttk.LabelFrame(actions_pane, text="⛏️ Mining", bootstyle=DANGER)
        mining_frame.grid(row=2, column=0, sticky=EW, pady=(0, 10))
        self.mine_button = ttk.Button(mining_frame, text="Start Mining", command=self._toggle_mining, bootstyle=DANGER)
        self.mine_button.pack(side=LEFT, padx=5, pady=5)
        ttk.Label(mining_frame, text="Status:").pack(side=LEFT, padx=(10, 0))
        ttk.Label(mining_frame, textvariable=self.mining_status_var).pack(side=LEFT, padx=5)

        received_data_frame = ttk.LabelFrame(actions_pane, text="📬 Received Trait Data", bootstyle=SUCCESS)
        received_data_frame.grid(row=3, column=0, sticky=NSEW, pady=(0, 10))
        actions_pane.rowconfigure(3, weight=1)
        received_data_frame.columnconfigure(0, weight=1)
        received_data_frame.rowconfigure(0, weight=1)
        self.received_data_tv = ttk.Treeview(received_data_frame, columns=("data_info",), show="", selectmode="none", bootstyle=SUCCESS)
        self.received_data_tv.column("#0", width=0, stretch=NO)
        self.received_data_tv.column("data_info", anchor=W)
        self.received_data_tv.grid(row=0, column=0, sticky=NSEW, padx=5, pady=5)
        rd_scroll = ttk.Scrollbar(received_data_frame, orient=VERTICAL, command=self.received_data_tv.yview, bootstyle="round-success")
        rd_scroll.grid(row=0, column=1, sticky=NS, pady=5)
        self.received_data_tv.config(yscrollcommand=rd_scroll.set)
        self._bind_mouse_scroll(self.received_data_tv)
        pw.add(actions_pane)

        log_pane = ttk.Frame(pw, padding=5)
        log_pane.columnconfigure(0, weight=1)
        log_pane.rowconfigure(0, weight=1)
        log_frame = ttk.LabelFrame(log_pane, text="📜 GUI Miner Log", bootstyle=SECONDARY)
        log_frame.grid(sticky=NSEW)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, wrap=tk.WORD)
        self.log_text.grid(row=0, column=0, sticky=NSEW, padx=5, pady=5)
        try:
            bg_color = self.style.colors.inputbg
            fg_color = self.style.colors.inputfg
            self.log_text.configure(bg=bg_color, fg=fg_color, insertbackground=fg_color)
        except Exception as e:
            pass
            # print(f"Could not style log_text: {e}") # Comment removed
        self.log_text.config(state=tk.DISABLED)
        self._bind_mouse_scroll(self.log_text)
        pw.add(log_pane)

        self._set_actions_enabled(False)

    def _set_actions_enabled(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        widgets_to_toggle = [
            self.load_genome_btn, self.trait_combo, self.consent_btn,
            self.upload_genome_btn, self.request_access_btn, self.copy_addr_button,
            self.mine_button
        ]
        entry_state = 'readonly' if enabled else 'disabled'

        try:
            self.address_display_entry.config(state=entry_state)
        except (tk.TclError, AttributeError):
            pass

        for widget in widgets_to_toggle:
            try:
                widget.config(state=state)
            except (tk.TclError, AttributeError):
                pass

        if not enabled:
            self.trait_combo.set('')
            self.trait_combo['values'] = []
            self.trait_combo.config(state=tk.DISABLED)
            self.logged_in_address_var.set("N/A")
            self.balance_var.set("0 GEN46")
            for item in self.received_data_tv.get_children():
                self.received_data_tv.delete(item)
            self.log_text.config(state=tk.NORMAL)
            self.log_text.delete('1.0', tk.END)
            self.log_text.config(state=tk.DISABLED)
            if self.gui_miner_process and self.gui_miner_process.is_alive():
                self._stop_gui_miner()
            self.mining_status_var.set("Idle")
            try:
                self.mine_button.config(text="Start Mining", bootstyle=DANGER)
            except (AttributeError, tk.TclError):
                pass
        else:
            self.trait_combo.config(state=tk.DISABLED)
            self.consent_btn.config(state=tk.DISABLED)
            self.last_processed_block_index = -1

    def _show_mnemonic_dialog(self, address, mnemonic):
        dialog = tk.Toplevel(self)
        dialog.title("🔒 New Wallet Created - SAVE MNEMONIC!")
        try:
            dialog.configure(bg=self.style.colors.bg)
        except Exception:
            pass
        dialog.geometry("600x250")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        pad = {"padx": 10, "pady": 5}

        ttk.Label(dialog, text="Your New Wallet Address:", font="-weight bold", bootstyle=PRIMARY).pack(pady=(10, 0))
        ttk.Label(dialog, text=address, font=("Courier", 10)).pack(**pad)
        ttk.Label(dialog, text="SAVE THIS MNEMONIC PHRASE SECURELY:", font="-weight bold", bootstyle=WARNING).pack(pady=(10, 0))

        mnemonic_text = scrolledtext.ScrolledText(dialog, height=4, width=70, wrap=tk.WORD, relief=tk.FLAT)
        try:
            bg = self.style.colors.inputbg
            fg = self.style.colors.inputfg
            mnemonic_text.configure(bg=bg, fg=fg, insertbackground=fg)
        except Exception:
            pass
        mnemonic_text.pack(**pad)
        mnemonic_text.insert(tk.END, mnemonic)
        mnemonic_text.config(state=tk.DISABLED)

        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=10)
        copy_status_var = tk.StringVar()
        copy_button = ttk.Button(button_frame, text="Copy Mnemonic", command=lambda m=mnemonic, s=copy_status_var: self._copy_text_to_clipboard(m, s, copy_button), bootstyle=SECONDARY)
        copy_button.pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="OK (I have saved it!)", command=dialog.destroy, bootstyle=PRIMARY).pack(side=tk.LEFT, padx=10)
        status_label = ttk.Label(dialog, textvariable=copy_status_var, bootstyle=SUCCESS)
        status_label.pack(pady=(0, 10))

        dialog.update_idletasks()
        main_win_x = self.winfo_rootx()
        main_win_y = self.winfo_rooty()
        main_win_width = self.winfo_width()
        main_win_height = self.winfo_height()
        dialog_width = dialog.winfo_width()
        dialog_height = dialog.winfo_height()
        x = main_win_x + (main_win_width // 2) - (dialog_width // 2)
        y = main_win_y + (main_win_height // 2) - (dialog_height // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.wait_window()

    def _copy_text_to_clipboard(self, text_to_copy, status_var, button_widget):
        try:
            self.clipboard_clear()
            self.clipboard_append(text_to_copy)
            original_text = button_widget['text']
            original_style = button_widget.cget('bootstyle')
            button_widget.config(text="Copied!", bootstyle=SUCCESS)
            if status_var:
                status_var.set("Copied!")
            self.after(1500, lambda: button_widget.config(text=original_text, bootstyle=original_style))
            if status_var:
                self.after(1500, lambda: status_var.set(""))
        except tk.TclError:
            if status_var:
                status_var.set("Clipboard unavailable?")
                self.after(3000, lambda: status_var.set(""))
        except Exception as e:
            if status_var:
                status_var.set(f"Error: {e}")
                self.after(3000, lambda: status_var.set(""))

    def _copy_address_to_clipboard(self):
        addr = self.logged_in_address_var.get()
        if addr and addr != "N/A":
            self._copy_text_to_clipboard(addr, None, self.copy_addr_button)

    def _create_wallet(self):
        new_mnemonic = generate_mnemonic()
        try:
            new_address = address_from_mnemonic(new_mnemonic)
            self._show_mnemonic_dialog(new_address, new_mnemonic)
            self.current_mnemonic = new_mnemonic
            self.current_address = new_address
            self.logged_in_address_var.set(self.current_address)
            self._set_actions_enabled(True)
            self.mnemonic_entry.delete(0, tk.END)
            self._update_balance()
            self._clear_loaded_traits()
            chain_snapshot = list(self.chain)
            self.last_processed_block_index = len(chain_snapshot) - 1
            self.last_displayed_block_index = -1
            for item in self.received_data_tv.get_children():
                self.received_data_tv.delete(item)
            for item in self.block_list_tv.get_children():
                self.block_list_tv.delete(item)
            self._log_message("Wallet Created. Mining Log Cleared.")
        except Exception as e:
            messagebox.showerror("Error Creating Wallet", f"{e}", parent=self)
            self._logout()

    def _restore_wallet(self):
        mnemonic = self.mnemonic_entry.get().strip()
        if not mnemonic:
            messagebox.showwarning("Input Missing", "Enter mnemonic.", parent=self)
            return
        try:
            self.current_address = address_from_mnemonic(mnemonic)
            self.current_mnemonic = mnemonic
            self.logged_in_address_var.set(self.current_address)
            self._set_actions_enabled(True)
            messagebox.showinfo("Wallet Restored", f"Logged in:\n{self.current_address}", parent=self)
            self._update_balance()
            self._clear_loaded_traits()
            chain_snapshot = list(self.chain)
            self.last_processed_block_index = len(chain_snapshot) - 1
            self.last_displayed_block_index = -1
            for item in self.received_data_tv.get_children():
                self.received_data_tv.delete(item)
            for item in self.block_list_tv.get_children():
                self.block_list_tv.delete(item)
            self._log_message("Wallet Restored. Mining Log Cleared.")
        except ValueError as e:
            messagebox.showerror("Restore Failed", f"{e}", parent=self)
            self._logout()
        except Exception as e:
            messagebox.showerror("Error", f"{e}", parent=self)
            self._logout()

    def _logout(self):
        self.current_address = None
        self.current_mnemonic = None
        self.logged_in_address_var.set("N/A")
        self._set_actions_enabled(False)
        self.mnemonic_entry.delete(0, tk.END)
        self.mnemonic_entry.config(show='*')
        self.last_displayed_block_index = -1
        self._log_message("User logged out.")

    def _update_balance(self):
        if self.current_address:
            balance = self.balances.get(self.current_address, 0)
            self.balance_var.set(f"{balance} GEN46")
        else:
            self.balance_var.set("0 GEN46")

    def _clear_loaded_traits(self):
        self.trait_combo.config(state=tk.DISABLED)
        self.trait_combo.set('')
        self.trait_combo['values'] = []
        self.consent_btn.config(state=tk.DISABLED)

    def _load_genome(self):
        if not self.current_address:
            messagebox.showwarning("Not Logged In", "Log in first.", parent=self)
            return
        tx = latest_genome_tx(self.chain, self.current_address)
        if not tx:
            messagebox.showinfo("No Genome", f"No genome for:\n{self.current_address}", parent=self)
            self._clear_loaded_traits()
            return
        traits = tx.get("traits", [])
        if traits:
            self.trait_combo.config(state="readonly", values=traits)
            self.trait_combo.current(0)
            self.consent_btn.config(state=tk.NORMAL)
            messagebox.showinfo("Genome Loaded", f"Loaded {len(traits)} traits.", parent=self)
        else:
            messagebox.showinfo("No Traits", "Upload tx has no traits.", parent=self)
            self._clear_loaded_traits()

    def _consent_trait(self):
        if not self.current_address:
            messagebox.showwarning("Not Logged In", "Log in first.", parent=self)
            return
        trait = self.trait_combo.get()
        if not trait:
            messagebox.showwarning("No Trait", "Select trait.", parent=self)
            return
        if has_consent(self.chain, self.current_address, trait):
            messagebox.showwarning("Consented", f"Consent for '{trait}' found.", parent=self)
            return
        pending = False
        for ptx in list(self.mempool):
             if (ptx.get("type") == "consent"
                 and ptx.get("user") == self.current_address
                 and ptx.get("trait") == trait):
                 pending = True
                 break
        if pending:
             messagebox.showwarning("Pending", f"Consent for '{trait}' in mempool.", parent=self)
             return

        tx_data = {
            "tx_id": str(uuid.uuid4()), "type": "consent",
            "user": self.current_address, "trait": trait, "timestamp": time.time()
        }
        self.mempool.append(tx_data)
        messagebox.showinfo("Queued", f"Consent for '{trait}' queued.", parent=self)

    def _request_access(self):
        if not self.current_address:
            messagebox.showwarning("Not Logged In", "Log in first.", parent=self)
            return
        requester = self.current_address
        target = simpledialog.askstring("Target Address", "Enter target:", parent=self)
        if not target:
            return
        target = target.strip()
        if not target.startswith("0x") or len(target) != 42:
            messagebox.showerror("Invalid Addr", "Invalid target.", parent=self)
            return
        if target == requester:
            messagebox.showwarning("Self Request", "Cannot request self.", parent=self)
            return
        trait = simpledialog.askstring("Trait", "Enter trait:", parent=self)
        if not trait:
            return
        trait = trait.strip()
        fee = 90
        requester_balance = self.balances.get(requester, 0)
        if requester_balance < fee:
            messagebox.showerror("Funds Error", f"Need {fee} GEN46.", parent=self)
            return
        if not has_consent(self.chain, target, trait):
            messagebox.showerror("Consent Error", f"No consent for '{trait}'.", parent=self)
            return
        tx_data = {
            "tx_id": str(uuid.uuid4()), "type": "request_access",
            "requester": requester, "target": target, "trait": trait, "timestamp": time.time()
        }
        self.mempool.append(tx_data)
        messagebox.showinfo("Queued", f"Access request queued.", parent=self)

    def _upload_genome(self):
        if not self.current_address:
            messagebox.showwarning("Not Logged In", "Log in first.", parent=self)
            return
        filepath = filedialog.askopenfilename(title="Select Genome JSON", filetypes=[("JSON", "*.json")], parent=self)
        if not filepath:
            return
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                genome_data = json.load(f)
            if not isinstance(genome_data, dict):
                raise ValueError("Not JSON obj.")
            required_keys = ["user_id", "traits"]
            if not all(k in genome_data for k in required_keys):
                raise ValueError("Missing keys.")
            if not isinstance(genome_data["traits"], dict):
                raise ValueError("'traits' not dict.")
            if genome_data["user_id"] != self.current_address:
                raise ValueError("Addr mismatch.")
            genome_str = json.dumps(genome_data, sort_keys=True, separators=(',', ':'))
            cid = hashlib.sha256(genome_str.encode()).hexdigest()
            tx = {
                "tx_id": str(uuid.uuid4()), "type": "upload_genome",
                "user": self.current_address, "traits": list(genome_data["traits"]),
                "genome_cid": cid, "timestamp": time.time()
            }
            self.mempool.append(tx)
            messagebox.showinfo("Queued", f"Genome upload queued.", parent=self)
        except Exception as e:
            messagebox.showerror("Upload Error", f"{e}", parent=self)

    def _toggle_mining(self):
        if not self.current_address:
            messagebox.showwarning("Not Logged In", "Log in first.", parent=self)
            return
        if Node is None:
            messagebox.showerror("Error", "Node missing.", parent=self)
            return
        if self.gui_miner_process and self.gui_miner_process.is_alive():
            self._stop_gui_miner()
        else:
            self._start_gui_miner()

    def _start_gui_miner(self):
        if not self.current_address:
            return
        self._log_message("Starting miner...")
        print(f"[GUI] Starting miner for {self.current_address[:10]}...")
        try:
            self.gui_miner_process = Node(
                -1, self.mempool, self.chain, self.balances,
                POW_DIFF, TXS_PER_BLOCK, self.current_address, self.log_queue
            )
            self.gui_miner_process.start()
            self.mine_button.config(text="Stop Mining", bootstyle=SUCCESS)
            self.mining_status_var.set("Active")
            self._log_message("Miner Started.")
        except Exception as e:
            self._log_message(f"ERROR start miner: {e}")
            messagebox.showerror("Mining Error", f"{e}", parent=self)
            self.gui_miner_process = None
            try:
                self.mine_button.config(text="Start Mining", bootstyle=DANGER)
            except tk.TclError:
                pass
            self.mining_status_var.set("Error")

    def _stop_gui_miner(self):
        miner_active = False
        if self.gui_miner_process and self.gui_miner_process.is_alive():
            miner_active = True
            self._log_message("Stopping miner...")
            print(f"[GUI] Stopping miner for {self.current_address[:10]}...")
            self.gui_miner_process.terminate()
            self.gui_miner_process.join(timeout=0.5)
        self.gui_miner_process = None
        try:
            self.mine_button.config(text="Start Mining", bootstyle=DANGER)
        except tk.TclError:
            pass
        self.mining_status_var.set("Idle")
        if self.current_address and miner_active:
            self._log_message("Miner Stopped.")

    def _log_message(self, msg: str):
        def update_log():
            if not self.log_text.winfo_exists():
                 return
            try:
                self.log_text.config(state=tk.NORMAL)
                self.log_text.insert(tk.END, f"{msg}\n")
                self.log_text.see(tk.END)
                self.log_text.config(state=tk.DISABLED)
            except tk.TclError:
                pass
        self.after(0, update_log)

    def _check_log_queue(self):
        try:
            while True:
                log_entry = self.log_queue.get_nowait()
                self._log_message(log_entry)
        except queue.Empty:
            pass
        except Exception as e:
            print(f"Log Q error: {e}")
        finally:
            if self.winfo_exists():
                 self.after(500, self._check_log_queue)

    def refresh(self):
        if not self.winfo_exists():
            return
        try:
            chain_snapshot = list(self.chain)
            mempool_snapshot = list(self.mempool)

            current_chain_len = len(chain_snapshot)
            if current_chain_len > self.last_displayed_block_index + 1:
                for i in range(self.last_displayed_block_index + 1, current_chain_len):
                    blk = chain_snapshot[i]
                    num_tx = len(blk.get("transactions", []))
                    block_hash = blk.get("hash", "N/A")[:10]
                    display_text = f"#{i} | {num_tx} tx | {block_hash}…"
                    iid = str(i)
                    self.block_list_tv.insert("", tk.END, iid=iid, values=(display_text,))
                    if i == current_chain_len - 1:
                        self.block_list_tv.see(iid)
                self.last_displayed_block_index = current_chain_len - 1

            self.mempool_tv.delete(*self.mempool_tv.get_children())
            for i, tx in enumerate(mempool_snapshot):
                who = tx.get("user") or tx.get("requester", "N/A")
                addr_short = f"{who[:8]}..." if isinstance(who, str) else "N/A"
                tx_type = tx.get("type", "N/A")
                tx_detail = ""
                if tx_type == 'upload_genome':
                    tx_detail = tx.get('genome_cid', '')[:8]+'...'
                elif tx_type == 'consent' or tx_type == 'request_access':
                     tx_detail = tx.get('trait', '')
                display_text = f"{tx_type.replace('_',' ').title()} : {addr_short} {tx_detail}"
                self.mempool_tv.insert("", tk.END, iid=f"mem_{i}", values=(display_text,))
            self.mem_frame.config(text=f" M Pending Tx ({len(mempool_snapshot)}) ")

            self._update_balance()

            if self.current_address and len(chain_snapshot) > self.last_processed_block_index + 1:
                self._update_received_data(chain_snapshot)

            if (self.gui_miner_process
                and not self.gui_miner_process.is_alive()
                and self.mining_status_var.get() == "Active"):
                print("[GUI] Miner stopped.")
                self._log_message("WARN: Miner stopped.")
                self._stop_gui_miner()

        except Exception as e:
            print(f"Refresh error: {e}")
        finally:
             if self.winfo_exists():
                self.after(self.refresh_ms, self.refresh)

    def _update_received_data(self, chain_snapshot):
        start_index = self.last_processed_block_index + 1
        new_items = []
        for i in range(start_index, len(chain_snapshot)):
            blk = chain_snapshot[i]
            block_index = blk.get("index", -1)
            for tx_idx, tx in enumerate(blk.get("transactions", [])):
                if (tx.get("type") == "request_access"
                    and tx.get("requester") == self.current_address
                    and "retrieved_value" in tx):
                    trait = tx.get("trait")
                    target = tx.get("target", "Unk")
                    value = tx.get("retrieved_value")
                    timestamp_val = tx.get("timestamp", 0)
                    try:
                        time_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(timestamp_val))
                    except ValueError:
                        time_str = "Invalid Date"
                    display_str = f"{time_str} - '{trait}' from {target[:10]}..: {value}"
                    iid = f"rec_{block_index}_{tx_idx}"
                    new_items.append((iid, display_str))
        if new_items:
            for iid, display_str in reversed(new_items):
                if not self.received_data_tv.exists(iid):
                    self.received_data_tv.insert("", 0, iid=iid, values=(display_str,))
        self.last_processed_block_index = len(chain_snapshot) - 1

    def _show_block_treeview(self, event):
        selection = self.block_list_tv.selection()
        if selection:
            block_iid = selection[0]
            try:
                block_index = int(block_iid)
                chain_snapshot = list(self.chain)
                if 0 <= block_index < len(chain_snapshot):
                    blk = chain_snapshot[block_index]
                else:
                     raise IndexError("Block index out of range")
                self.detail_txt.config(state=tk.NORMAL)
                self.detail_txt.delete("1.0", tk.END)
                self.detail_txt.insert(tk.END, json_pretty(blk))
                self.detail_txt.config(state=tk.DISABLED)
            except (IndexError, ValueError) as e:
                self.detail_txt.config(state=tk.NORMAL)
                self.detail_txt.delete("1.0", tk.END)
                self.detail_txt.insert(tk.END, f"Error loading block '{block_iid}': {e}")
                self.detail_txt.config(state=tk.DISABLED)

    def _search_addr(self):
        addr = self.search_entry.get().strip()
        self.search_balance_var.set("")
        for item in self.tree.get_children():
             self.tree.delete(item)

        if not addr:
            messagebox.showwarning("Input Missing", "Enter addr.", parent=self)
            return
        if not addr.startswith("0x") or len(addr) != 42:
            messagebox.showerror("Invalid Addr", "Invalid format.", parent=self)
            return

        balance = self.balances.get(addr, 0)
        self.search_balance_var.set(f"Balance {addr[:10]}..: {balance} GEN46")

        found = 0
        chain_snapshot = list(self.chain)
        for i, blk in enumerate(chain_snapshot):
            tx_list = blk.get("transactions", [])
            for tx in tx_list:
                involved = addr in (
                    tx.get("user"), tx.get("requester"), tx.get("target")
                )
                if involved:
                    timestamp_val = tx.get("timestamp", 0)
                    try:
                        time_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(timestamp_val))
                    except ValueError:
                        time_str = "Invalid Date"
                    tag = 'oddrow' if found % 2 == 0 else 'evenrow'
                    self.tree.insert(
                        "", tk.END,
                        values=(
                            i, tx.get("tx_id", "N/A")[:8], tx.get("type", "N/A"),
                            tx.get("trait", ""), time_str,
                        ),
                        tags=(tag,)
                    )
                    found += 1
        if found == 0:
            messagebox.showinfo("No Results", f"No tx found for:\n{addr}", parent=self)

def start_gui(chain, mempool, balances, log_queue):
    selected_theme = 'cyborg'
    print(f"[GUI] Starting with theme: {selected_theme}")
    app = BlockExplorer(chain, mempool, balances, log_queue=log_queue, theme=selected_theme)
    app.mainloop()

if __name__ == '__main__':
    import secrets
    import hashlib
    from multiprocessing import Manager, Queue

    def _make_address_local(seed: str) -> str:
        h = hashlib.sha256(seed.encode()).hexdigest()
        return "0x" + h[-40:]
    _TEST_WORD_LIST = ['test', 'word'] * 12
    def _generate_mnemonic_local(num_words: int = 24) -> str:
        return " ".join([secrets.choice(_TEST_WORD_LIST) for _ in range(num_words)])
    def _address_from_mnemonic_local(mnemonic: str) -> str:
        words = mnemonic.strip().split()
        if not words or len(words) < 12:
             raise ValueError("Invalid mnemonic phrase format.")
        return _make_address_local(mnemonic.strip())

    try:
        import address_utils
        if address_utils.generate_mnemonic.__module__ != 'address_utils':
             raise ImportError
    except (NameError, ModuleNotFoundError, ImportError):
        print("Using embedded fallback address functions for testing.")
        generate_mnemonic = _generate_mnemonic_local
        address_from_mnemonic = _address_from_mnemonic_local

    if Node is None:
        print("FATAL: Node class not available for test run.")
        exit()

    print("Running GUI test mode (Strict Style Cleanup)...")
    manager = Manager()
    test_chain = manager.list()
    test_mempool = manager.list()
    test_balances = manager.dict()
    test_log_queue = Queue()

    genesis_hash = hashlib.sha256(b"genesis_block").hexdigest()
    test_chain.append({
        "index": 0, "timestamp": time.time(), "miner": "0x"+"0"*40,
        "transactions": [], "previous_hash": "0"*64, "hash": genesis_hash, "nonce": 0
    })

    mnemo1 = generate_mnemonic()
    addr1 = address_from_mnemonic(mnemo1)
    mnemo2 = generate_mnemonic()
    addr2 = address_from_mnemonic(mnemo2)
    test_balances[addr1] = 150
    test_balances[addr2] = 50
    print(f"Test Addr 1: {addr1}")
    print(f"Test Mnem 1: <Hidden>")
    print(f"Test Addr 2: {addr2}")

    test_mempool.append({
        "tx_id": str(uuid.uuid4()), "type": "consent", "user": addr1,
        "trait": "BRCA1", "timestamp": time.time()
    })
    test_mempool.append({
        "tx_id": str(uuid.uuid4()), "type": "upload_genome", "user": addr2,
        "traits": ["APOE", "FTO"], "genome_cid": "cid_"+secrets.token_hex(4),
        "timestamp": time.time()
    })

    start_gui(test_chain, test_mempool, test_balances, log_queue=test_log_queue)