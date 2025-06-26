from __future__ import annotations

import json
import os
import time
import random
import hashlib
import uuid
import queue
from multiprocessing import Process, Queue
from typing import Dict, Any, List, Optional

from address_utils import make_address
from blockchain import Block
from genome_generator import TRAIT_OPTIONS

GEN_REWARD_CONSENT = 46
GEN_REWARD_BLOCK= 150
FEE_ACCESS = 90

class Node(Process):

    def __init__(self, node_id: int, mempool, chain, balances: Dict[str, int],
                 difficulty: int = 4, max_txs: int = 8,
                 miner_address: Optional[str] = None,
                 log_queue: Optional[Queue] = None):
        super().__init__(daemon=True)
        self.node_id = node_id
        if miner_address:
            self.addr = miner_address
        else:
            self.addr = make_address(f"miner-{self.node_id}")
        self.mempool = mempool
        self.chain = chain
        self.balances = balances
        self.diff = difficulty
        self.max_txs = max_txs
        self.log_queue = log_queue

    def _log(self, message: str):
        if self.log_queue:
            try:
                log_prefix = f"[{self.node_id if self.node_id != -1 else 'GUI'}]"
                log_entry = f"{time.strftime('%H:%M:%S')} {log_prefix} {message}"
                self.log_queue.put_nowait(log_entry)
            except queue.Full:
                pass
            except Exception as e:
                print(f"Error sending log: {e}")

    def _credit(self, addr: str, amt: int):
        self.balances[addr] = self.balances.get(addr, 0) + amt

    def _debit(self, addr: str, amt: int):
        new_balance = self.balances.get(addr, 0) - amt
        if new_balance < 0:
            self._log(f"WARN: Debited {addr[:6]} below zero!")
        self.balances[addr] = new_balance

    def _has_consent(self, target: str, trait: str) -> bool:
        chain_snapshot = list(self.chain)
        for blk in reversed(chain_snapshot):
            block_transactions = blk.get("transactions", [])
            for tx in block_transactions:
                if (tx.get("type") == "consent" and tx.get("user") == target and
                        tx.get("trait") == trait):
                    return True
        return False

    def run(self):
        node_name = f"Miner {self.node_id}" if self.node_id != -1 else "GUI Miner"
        self._log(f"Process started. Addr: {self.addr[:10]}... Diff: {self.diff}")
        print(f"[{node_name} Addr {self.addr[:6]}] Ready (diff={self.diff})")

        while True:
            if not self.mempool:
                time.sleep(random.uniform(1.0, 2.0))
                continue

            self._log("Checking mempool...")
            tx_batch: List[Dict[str, Any]] = []
            mempool_snapshot = list(self.mempool)
            current_balances_check = self.balances.copy()
            temp_tx_batch_candidates = []

            for raw_tx in mempool_snapshot:
                if len(temp_tx_batch_candidates) >= self.max_txs:
                    break
                temp_tx_batch_candidates.append(raw_tx)

            processed_indices = set()
            self._log(f"Validating {len(temp_tx_batch_candidates)} candidate txs...")
            for idx, raw_tx in enumerate(temp_tx_batch_candidates):
                if len(tx_batch) >= self.max_txs:
                    break

                ttype = raw_tx.get("type")
                valid_tx_in_context = False

                if ttype == "consent":
                    user = raw_tx.get("user")
                    trait = raw_tx.get("trait")
                    if user and trait and not self._has_consent(user, trait):
                        current_balances_check[user] = current_balances_check.get(user, 0) + GEN_REWARD_CONSENT
                        valid_tx_in_context = True
                elif ttype == "request_access":
                    req = raw_tx.get("requester")
                    tgt = raw_tx.get("target")
                    trait = raw_tx.get("trait")
                    if req and tgt and trait:
                        if self._has_consent(tgt, trait) and current_balances_check.get(req, 0) >= FEE_ACCESS:
                            current_balances_check[req] = current_balances_check.get(req, 0) - FEE_ACCESS
                            current_balances_check[tgt] = current_balances_check.get(tgt, 0) + FEE_ACCESS
                            valid_tx_in_context = True
                elif ttype == "upload_genome":
                    valid_tx_in_context = True
                elif ttype == "reward":
                    continue

                if valid_tx_in_context:
                    tx_batch.append(raw_tx)
                    processed_indices.add(idx)

            if not tx_batch:
                self._log("No valid transactions for new block.")
                time.sleep(random.uniform(0.5, 1.5))
                continue

            self._log(f"Selected {len(tx_batch)} valid txs.")

            
            reward_tx = {
                "tx_id": str(uuid.uuid4()),
                "type": "reward",
                "user": self.addr,
                "amount": GEN_REWARD_BLOCK,
                "timestamp": time.time()
            }
            full_tx_batch = tx_batch + [reward_tx]

            self._log(f"Attempting PoW for block #{len(list(self.chain))}...")
            new_block_instance = None
            new_block_dict = None
            try:
                if not self.chain:
                    self._log("ERROR: Chain empty.")
                    continue
                prev_block = self.chain[-1]
                prev_hash = prev_block["hash"]
                new_index = prev_block["index"] + 1
                new_block_instance = Block(new_index, full_tx_batch, prev_hash=prev_hash,
                                           difficulty=self.diff, miner=self.addr)
                new_block_dict = new_block_instance.to_dict()
                self._log(f"Mined Block #{new_index}! Hash: {new_block_instance.hash[:8]}...")

            except Exception as e:
                self._log(f"ERROR during PoW/Block creation: {e}")
                continue

            if new_block_dict:
                block_added_successfully = False
                try:
                    self.chain.append(new_block_dict)
                    block_added_successfully = True
                    self._log(f"Appended Block #{new_block_dict['index']} to shared chain.")

                    self._credit(self.addr, GEN_REWARD_BLOCK)
                    self._log(f"Credited self {GEN_REWARD_BLOCK} reward.")

                    balances_updated = True
                    for tx in tx_batch:
                        tx_type = tx.get("type")
                        if tx_type == "consent":
                            self._credit(tx["user"], GEN_REWARD_CONSENT)
                        elif tx_type == "request_access":
                            req = tx.get("requester")
                            tgt = tx.get("target")
                            self._debit(req, FEE_ACCESS)
                            self._credit(tgt, FEE_ACCESS)
                    self._log("Applied transaction balance changes.")

                    mined_tx_ids = {tx['tx_id'] for tx in tx_batch}
                    num_removed = 0
                    try:
                        current_mempool = list(self.mempool)
                        new_mempool_list = [tx for tx in current_mempool if tx['tx_id'] not in mined_tx_ids]
                        if len(new_mempool_list) < len(current_mempool):
                            self.mempool[:] = new_mempool_list
                            num_removed = len(current_mempool) - len(new_mempool_list)
                        self._log(f"Removed {num_removed} txs from mempool.")
                    except Exception as e:
                        self._log(f"Error removing txs from mempool: {e}")

                    print(f"[{node_name} Addr {self.addr[:6]}] Completed Block #{new_block_dict['index']} | {len(full_tx_batch)} txs ({num_removed} removed) | Rew: {GEN_REWARD_BLOCK} | Hash: {new_block_dict['hash'][:8]}...")

                except Exception as e:
                    self._log(f"ERROR appending block or updating state: {e}")

            time.sleep(random.uniform(0.1, 0.5))

def generate_genome_uploads(mempool, data_dir: str = "genome_data", poll: int = 3):
    base_path = os.path.dirname(os.path.abspath(__file__))
    folder = os.path.join(base_path, data_dir)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        print(f"[Genome Uploader Error] Cannot create/access {folder}: {e}")
        return

    seen = set()
    print("[Genome Uploader] Started - Monitoring", folder)
    while True:
        try:
            found_new = False
            for fn in os.listdir(folder):
                if not fn.endswith(".json") or fn in seen:
                    continue
                filepath = os.path.join(folder, fn)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        genome = json.load(f)
                    user_id = genome.get("user_id")
                    traits_dict = genome.get("traits")
                    if not user_id or not isinstance(traits_dict, dict):
                        print(f"[Genome Uploader WARN] Skipping invalid file: {fn}")
                        seen.add(fn)
                        continue

                    genome_str_sorted = json.dumps(genome, sort_keys=True, separators=(',', ':'))
                    cid = hashlib.sha256(genome_str_sorted.encode('utf-8')).hexdigest()
                    upload_tx = {
                        "tx_id": str(uuid.uuid4()),
                        "type": "upload_genome",
                        "user": user_id,
                        "traits": list(traits_dict.keys()),
                        "genome_cid": cid,
                        "timestamp": time.time()
                    }
                    mempool.append(upload_tx)
                    print(f"[Genome Uploader] Queued {fn} for user {user_id[:8]}... (CID: {cid[:8]}...)")
                    seen.add(fn)
                    found_new = True
                except json.JSONDecodeError:
                    print(f"[Genome Uploader WARN] Skipping invalid JSON file: {fn}")
                    seen.add(fn)
                except FileNotFoundError:
                    print(f"[Genome Uploader WARN] File disappeared before reading: {fn}")
                    seen.add(fn)
                except Exception as e:
                    print(f"[Genome Uploader Error] Processing {fn}: {e}")
                    seen.add(fn)

            if not found_new:
                time.sleep(poll)

        except FileNotFoundError:
            print(f"[Genome Uploader Error] Directory not found: {folder}. Stopping.")
            break
        except Exception as e:
            print(f"[Genome Uploader Error] Unexpected error monitoring directory: {e}")
            time.sleep(poll * 2)