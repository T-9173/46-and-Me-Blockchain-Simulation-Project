# 46-and-Me Blockchain Simulation Project

This repository contains a Python-based blockchain simulation designed to explore concepts related to decentralized genetic data management, user consent, and secure data access. It simulates a network of users and miners, allowing for the creation of blocks, processing of transactions, and interaction with genetic traits.

### Features

* **Blockchain Core:** Implements a basic blockchain with Proof-of-Work (PoW) consensus for block creation and verification.
* **Decentralized Network Simulation:** Orchestrates multiple miner nodes that compete to mine blocks and a mempool for pending transactions.
* **Genetic Data Management:**
    * **Synthetic Genome Generation:** Automatically generates realistic synthetic genetic data (traits) for simulated users.
    * **Genome Uploads:** Users can upload their synthetic genome data to the blockchain.
* **Consent and Access Control:**
    * **Trait Consent:** Users can explicitly grant consent for specific genetic traits to be accessed by others.
    * **Access Requests:** Other users can request access to consented traits, with a simulated fee mechanism.
    * **Trait Data Retrieval:** When access is granted, the requesting user receives the specific trait data.
* **Wallet Management:** Includes utilities for generating and restoring cryptographic wallet addresses and mnemonic phrases.
* **Graphical User Interface (GUI):** A Tkinter-based application (`ttkbootstrap` styled) provides a visual interface to:
    * Explore blockchain blocks and their details.
    * View pending transactions in the mempool.
    * Manage user wallets (create, restore, view balance).
    * Initiate genome uploads, trait consents, and access requests.
    * Start/stop a GUI-integrated miner for the current wallet.
    * Display received trait data from access requests.
* **Transaction Types:** Supports `upload_genome`, `consent`, `request_access`, and `reward` transactions.

### How It Works

The simulation sets up a network with a central shared memory for the blockchain (`chain`), pending transactions (`mempool`), and user balances (`balances`).

1.  **Blockchain Initialization:** A genesis block is created to start the chain.
2.  **Genome Generation & Upload:** A background process continuously generates new synthetic genome data. Another process monitors this data and creates `upload_genome` transactions for the mempool.
3.  **Miners:** Multiple `Node` processes act as miners. They:
    * Listen for transactions in the `mempool`.
    * Select a batch of valid transactions.
    * Add a `reward` transaction for themselves.
    * Mine a new block by solving a Proof-of-Work puzzle (finding a nonce that produces a hash starting with a certain number of zeros).
    * Append the newly mined block to the shared `chain` and update `balances` based on the transactions included.
4.  **Transactions:**
    * **Consent:** When a user consents to a trait, a `consent` transaction is added to the mempool. Once mined, the user receives a `GEN46` token reward.
    * **Request Access:** A user can initiate a `request_access` transaction for a specific trait from another user. This transaction includes a fee. If the target user has consented to that trait, and the requester has sufficient funds, the transaction is valid and once mined, the fee is transferred to the target, and the trait data is "retrieved".
5.  **GUI:** The `gui.py` provides a real-time view of the blockchain, mempool, and allows users to interact with their wallet and initiate various transactions, demonstrating the application's functionality. Random consent and access requests are also simulated in the background.

### Getting Started

To run this project, you will need Python 3.7+ and `ttkbootstrap`.

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/T-9173/46-and-Me-Blockchain-Simulation-Project.git
    cd BlockchainProject
    ```
    
2.  **Install Dependencies:**
    ```bash
    pip install ttkbootstrap
    ```
    (Other standard libraries like `tkinter`, `json`, `hashlib`, `multiprocessing`, `threading`, `random`, `uuid`, `os`, `time`, `secrets`, `platform`, `queue` are typically included with Python)

3.  **Run the Simulation:**
    ```bash
    python run_simulation.py
    ```
    This script will start the blockchain, a genome generator, transaction spammers (for consents and access requests), multiple miner nodes, and the graphical user interface.

### Project Structure

* `address_utils.py`: Utility functions for generating blockchain addresses and mnemonic phrases.
* `blockchain.py`: Defines the `Block` and `Blockchain` classes, handling core blockchain logic, Proof-of-Work, and block verification.
* `genome_generator.py`: Contains logic to generate synthetic genetic data (traits) and to simulate live genome file generation.
* `gui.py`: Implements the Tkinter-based graphical user interface (GUI) for the blockchain explorer, wallet management, and interaction with the simulation.
* `node.py`: Defines the `Node` (miner) class responsible for picking transactions from the mempool, mining new blocks, and updating balances. It also includes the `generate_genome_uploads` function.
* `run_simulation.py`: The main script to initialize and run the entire blockchain simulation, orchestrating all the components.
* `.gitignore`: Specifies files and directories to be ignored by Git.
* `README.md`: This project README file.

### License

This project is open-sourced under the MIT License.
