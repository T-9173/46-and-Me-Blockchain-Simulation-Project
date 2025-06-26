from __future__ import annotations

import hashlib
import json
import time
from typing import List, Dict, Any, Tuple


def sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()



class Block:

    def __init__(self, index: int, txs: List[Dict[str, Any]], *,
                 prev_hash: str, difficulty: int = 4, miner: str = "0x0") -> None:
        self.index        = index
        self.timestamp    = time.time()
        self.miner        = miner
        self.transactions = txs
        self.previous_hash= prev_hash
        self.nonce, self.hash = self._mine(difficulty)

    def _serialised(self, nonce: int) -> str:
        return json.dumps({
            "index"       : self.index,
            "timestamp"   : self.timestamp,
            "miner"       : self.miner,
            "transactions": self.transactions,
            "previous_hash": self.previous_hash,
            "nonce"       : nonce,
        }, sort_keys=True)

    def _mine(self, diff: int) -> Tuple[int, str]:
        prefix = "0" * diff
        nonce  = 0
        while True:
            h = sha256(self._serialised(nonce))
            if h.startswith(prefix):
                return nonce, h
            nonce += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index"       : self.index,
            "timestamp"   : self.timestamp,
            "miner"       : self.miner,
            "transactions": self.transactions,
            "previous_hash": self.previous_hash,
            "hash"        : self.hash,
            "nonce"       : self.nonce,
        }

    @staticmethod
    def verify(block: Dict[str, Any], difficulty: int) -> bool:
        expected = sha256(json.dumps({k: block[k] for k in (
            "index","timestamp","miner","transactions","previous_hash","nonce")}, sort_keys=True))
        return (expected == block["hash"] and
                block["hash"].startswith("0"*difficulty))



class Blockchain:

    def __init__(self, chain_proxy, *, genesis_difficulty: int = 2) -> None:
        self.chain = chain_proxy  
        if len(self.chain) == 0:
            self._create_genesis(genesis_difficulty)

    def _create_genesis(self, difficulty: int):
        g = Block(0, [], prev_hash="0"*64, difficulty=difficulty, miner="0x00")
        self.chain.append(g.to_dict())
        print(f"[Genesis] {g.hash[:16]}… created")

    def latest(self) -> Dict[str, Any]:
        return self.chain[-1]

    def add_block(self, block_dict: Dict[str, Any], difficulty: int) -> bool:
        if block_dict["previous_hash"] != self.latest()["hash"]:
            return False 
        if not Block.verify(block_dict, difficulty):
            return False
        self.chain.append(block_dict)
        return True
