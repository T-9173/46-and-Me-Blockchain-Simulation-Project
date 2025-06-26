from __future__ import annotations

import time
import threading
import random
import uuid
import os
from multiprocessing import Manager, Process, Queue

from address_utils import make_address
from blockchain import Blockchain
from node import Node, generate_genome_uploads
from genome_generator import live_genome_generator, TRAIT_OPTIONS 
from gui import start_gui

NUM_USERS = 40
NUM_MINERS = 5
POW_DIFF = 4
TXS_PER_BLOCK = 8
INITIAL_BALANCE = 100


def simulate_random_consents(mempool_proxy, addresses, traits_list):
    print("[Sim Consent] Started - Randomly consenting traits...")
    while True:
        try:
            user_addr = random.choice(addresses)
            trait_to_consent = random.choice(traits_list)
            consent_tx = {
                "tx_id": str(uuid.uuid4()),
                "type": "consent",
                "user": user_addr,
                "trait": trait_to_consent,
                "timestamp": time.time()
            }
            mempool_proxy.append(consent_tx)
            time.sleep(random.uniform(5, 15))
        except Exception as e:
            print(f"[Sim Consent Error] {e}")
            time.sleep(10)

def spam_access(mempool_proxy, user_addrs_list):
    print("[Sim Access] Started - Randomly requesting access...")
    traits = ["BRCA1", "APOE", "CYP2C19", "FTO_rs9939609"]
    while True:
        try:
            req = random.choice(user_addrs_list)
            possible_targets = [u for u in user_addrs_list if u != req]
            if not possible_targets:
                time.sleep(1)
                continue
            tgt = random.choice(possible_targets)
            mempool_proxy.append({
                "tx_id": str(uuid.uuid4()),
                "type": "request_access",
                "requester": req,
                "target": tgt,
                "trait": random.choice(traits),
                "timestamp": time.time()
            })
            time.sleep(random.uniform(3, 6))
        except Exception as e:
            print(f"[Sim Access Error] {e}")
            time.sleep(10)


if __name__ == "__main__":
    print(f"Initializing simulation: {NUM_USERS} users, {NUM_MINERS} miners, Difficulty={POW_DIFF}")
    mgr = Manager()
    mempool = mgr.list()
    chain = mgr.list()
    balances = mgr.dict()
    gui_log_queue = Queue() # Queue for GUI miner logs

    user_addrs = [make_address(f"user-{i}") for i in range(NUM_USERS)]
    miner_addrs = [make_address(f"miner-{i}") for i in range(NUM_MINERS)]
    all_addrs = user_addrs + miner_addrs
    for a in all_addrs:
        balances[a] = INITIAL_BALANCE

    Blockchain(chain) 
    if not chain:
        print("CRITICAL ERROR: Blockchain failed to initialize.")
        exit()
    print(f"Blockchain initialized, Genesis hash: {chain[0]['hash'][:10]}...")

    Process(target=live_genome_generator, args=(2,), daemon=True).start()
    Process(target=generate_genome_uploads, args=(mempool,), daemon=True).start()
    print("Started Genome Generator and Uploader processes...")

    available_traits = list(TRAIT_OPTIONS.keys())

    consent_proc = Process(target=simulate_random_consents, args=(mempool, user_addrs, available_traits), daemon=True)
    consent_proc.start()
    access_proc = Process(target=spam_access, args=(mempool, user_addrs), daemon=True) 
    access_proc.start()

    miners: list[Process] = []
    print("Starting Miners...")
    for i in range(NUM_MINERS):
        p = Node(i, mempool, chain, balances,
                 difficulty=POW_DIFF, max_txs=TXS_PER_BLOCK, log_queue=None) 
        p.start()
        miners.append(p)
        print(f"  Miner {i} started (Addr: {p.addr[:10]}...)")

    print("Starting GUI...")
    gui_thread = threading.Thread(target=start_gui, args=(chain, mempool, balances, gui_log_queue), daemon=True)
    gui_thread.start()

    print("\n[Simulation Running] Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(2) 
            chain_len = len(list(chain))
            mempool_len = len(list(mempool))
            tip_hash = chain[-1]['hash'][:8] if chain_len > 0 else "N/A"
            print(f"[Status]  blocks={chain_len}  mempool={mempool_len}  tip={tip_hash}…")
            if not gui_thread.is_alive():
                print("[Sim] GUI thread terminated, stopping simulation.")
                break
    except KeyboardInterrupt:
        print("\n[Simulation Stopping] Terminating processes...")
    finally:
        if consent_proc.is_alive():
            consent_proc.terminate()
        if access_proc.is_alive():
            access_proc.terminate()
        for i, p in enumerate(miners):
            if p.is_alive():
                p.terminate()
                print(f"  Miner {i} terminated.")
        print("All miners stopped.")
        if gui_thread.is_alive():
            print("[Sim] GUI thread still alive (may need force close if window open)")
        print("Simulation finished. Goodbye!")