
from __future__ import annotations

import os, json, random, time
from itertools import count
from typing import Dict, Any

from address_utils import make_address


TRAIT_OPTIONS = {
    # Cancer‑related
    "BRCA1": ["c.68_69delAG", "c.5266dupC", "wildtype"],
    "BRCA2": ["c.5946delT", "c.7617+1G>T", "wildtype"],
    # Neuro / cognitive
    "APOE": ["ε2/ε2", "ε2/ε3", "ε3/ε3", "ε3/ε4", "ε4/ε4"],
    "COMT_V158M": ["Val/Val", "Val/Met", "Met/Met"],
    "DRD2_Taq1A": ["TT", "TC", "CC"],
    # Metabolism / drug response
    "CYP2C19": ["*1/*1", "*1/*2", "*1/*3", "*2/*2", "*17/*17"],
    "TPMT": ["*1/*1", "*1/*3A", "*3A/*3A"],
    "UGT1A1_28": ["6/6", "6/7", "7/7"],
    "VKORC1": ["GG", "GA", "AA"],
    # Cardiovascular / clotting
    "MTHFR_C677T": ["CC", "CT", "TT"],
    "FactorV_Leiden": ["GG", "GA", "AA"],
    # Immunity / infectious disease
    "HLA_DQB1": ["*03:01", "*06:02", "*02:01"],
    "CCR5_Δ32": ["Δ32/Δ32", "WT/Δ32", "WT/WT"],
    # Nutrition & fitness
    "FTO_rs9939609": ["AA", "AT", "TT"],
    "LCT_rs4988235": ["TT", "TC", "CC"],
    "ACTN3_R577X": ["RR", "RX", "XX"],
    # Blood disorders
    "HBB_Sickle": ["AA", "AS", "SS"],
    "G6PD": ["Normal", "Carrier", "Deficient"],
    # Alcohol response
    "ALDH2": ["*1/*1", "*1/*2", "*2/*2"],
    # Additional markers for realism
    "ABO_BloodType": ["O", "A", "B", "AB"],
    "ACE_I/D": ["II", "ID", "DD"],
    "SLCO1B1": ["*1a/*1a", "*1a/*5", "*5/*5"],
    "CYP2D6": ["*1/*1", "*1/*4", "*4/*4", "*1/*10"],
    "NAT2": ["Rapid", "Intermediate", "Slow"],
}



def _random_genome(addr: str, alias: str) -> Dict[str,Any]:
    return {
        "user_id": addr,
        "alias"  : alias,
        "traits" : {gene: random.choice(alleles)
                     for gene, alleles in TRAIT_OPTIONS.items()}
    }



def live_genome_generator(interval: int = 10, output_dir: str = "genome_data") -> None:
    """Write a new genome JSON every *interval* seconds."""
    base = os.path.dirname(os.path.abspath(__file__))
    out  = os.path.join(base, output_dir); os.makedirs(out, exist_ok=True)

    # Determine next alias index
    existing  = [f for f in os.listdir(out) if f.startswith("user") and f.endswith(".json")]
    next_idx  = max([int(f[4:-5]) for f in existing if f[4:-5].isdigit()] or [0]) + 1

    for idx in count(next_idx):
        alias   = f"user{idx}"
        address = make_address(alias)
        genome  = _random_genome(address, alias)

        with open(os.path.join(out, f"{alias}.json"), "w") as fp:
            json.dump(genome, fp, indent=2)
        print(f"[GenomeGen] wrote {alias}.json → {address[:10]}…")
        time.sleep(interval)

if __name__ == "__main__":
    live_genome_generator(interval=2)
