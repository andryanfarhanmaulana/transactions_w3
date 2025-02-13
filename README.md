# transactions_w3: Cross-Chain Bridge Event Listener

This repository contains a Python-based simulation of a crucial component in a cross-chain bridge system: the Event Listener, also known as a Relayer or Oracle. This script is designed to listen for specific events on a source blockchain and trigger corresponding actions on a destination blockchain.

It is architected to be robust, scalable, and illustrative of real-world decentralized application backends.

## Concept

A cross-chain bridge allows users to transfer assets or data from one blockchain (e.g., Ethereum) to another (e.g., Polygon). A common mechanism for this is "lock-and-mint" or "burn-and-release":

1.  **Lock/Burn**: A user locks tokens in a smart contract on the source chain. This action emits an event, like `CrossChainTransferInitiated`.
2.  **Listen**: Off-chain services, called listeners or relayers, constantly monitor the source chain for this specific event.
3.  **Verify**: Upon detecting an event, the listener waits for a few blocks to ensure the transaction is final (to avoid processing transactions from chain re-organizations).
4.  **Relay/Mint**: The listener then submits a new transaction to a smart contract on the destination chain, providing proof of the original event. This new transaction might mint an equivalent amount of wrapped tokens or release pre-existing tokens to the user's address on the new chain.

This script simulates the **listener (Relayer)** part of this process (steps 2, 3, and 4).

## Code Architecture

The script is designed with a clear separation of concerns, using several classes to handle different aspects of the process.

```
+-------------------------+
|   BridgeEventListener   | (Main Orchestrator)
| - Listens for events    |
| - Manages main loop     |
+-----------+-------------+
            |
            | uses
            v
+-------------------------+      +-------------------------+
|   BlockchainConnector   |----->|         web3.py         |
| - Manages RPC connection|      | (Blockchain Interaction)  |
| - Handles reconnections |      +-------------------------+
+-------------------------+
            |
            | uses
            v
+-------------------------+      +-------------------------+
|   TransactionProcessor  |----->|       StateManager      |
| - Builds & signs txs    |      | - Prevents double-spend |
| - Submits to dest chain |      | - Persists state to file|
+-------------------------+      +-------------------------+

```

-   **`Config`**: A centralized class to hold all configuration parameters, such as RPC URLs, contract addresses, and private keys. It reads from environment variables for security and flexibility.
-   **`BlockchainConnector`**: A utility class that abstracts the `web3.py` connection logic. It handles establishing the connection and provides a stable `Web3` instance, including logic for PoA (Proof of Authority) chains.
-   **`StateManager`**: Manages the state of which transactions have already been processed. It loads and saves a list of processed transaction hashes to a JSON file (`processed_transactions_state.json`) to prevent duplicate processing, even if the script restarts.
-   **`TransactionProcessor`**: Responsible for the "action" part. When an event is passed to it, this class constructs, signs, and (in a real scenario) sends the transaction to the destination chain to complete the cross-chain transfer.
-   **`BridgeEventListener`**: The core class that ties everything together. It initializes all other components, runs the main polling loop to check for new events on the source chain, and orchestrates the flow: **detect -> validate -> process -> mark as complete**.

## How it Works

1.  **Initialization**: 
    - The `BridgeEventListener` is instantiated.
    - It creates `BlockchainConnector` instances for both the source and destination chains.
    - It initializes the `StateManager` to load the history of any previously processed transactions.
    - It creates a `TransactionProcessor` configured for the destination chain, armed with the relayer's private key.

2.  **Listening Loop**:
    - The `listen()` method starts an infinite loop.
    - In each iteration, it checks the latest block number on the **source chain**.
    - To avoid acting on unconfirmed blocks, it only scans up to `latest_block - CONFIRMATION_BLOCKS`.
    - It uses `web3.py`'s `create_filter` to efficiently query a range of blocks for the `CrossChainTransferInitiated` event from the specified bridge contract.

3.  **Event Handling**:
    - If new events are found, the script iterates through them.
    - For each event, it performs two checks:
        1.  **Destination Match**: It verifies that the `destinationChainId` in the event data matches the chain this listener is configured to handle. This allows multiple listeners to operate on the same source contract without interfering.
        2.  **Duplicate Check**: It asks the `StateManager` if the event's transaction hash has already been processed. If so, it's skipped.

4.  **Transaction Processing (Simulation)**:
    - If an event is valid and new, it's passed to the `TransactionProcessor`.
    - The processor extracts the `recipient`, `amount`, and `nonce` from the event log.
    - It builds a new transaction to call the `releaseTokens` function on the destination bridge contract.
    - It signs this transaction using the relayer's private key.
    - **Crucially, in this simulation, the transaction is *not* sent.** The script logs the action and the raw signed transaction to the console. To send it for real, one would uncomment the `w3.eth.send_raw_transaction` line.

5.  **State Update**:
    - After successfully processing an event (or simulating it), the `StateManager` is called to `mark_as_processed()`. 
    - This adds the source transaction hash to its set and immediately saves the updated set to `processed_transactions_state.json`.

6.  **Loop and Repeat**:
    - The script then sleeps for a configured interval (`POLLING_INTERVAL_SECONDS`) before starting the next polling cycle.

## Usage Example

1.  **Prerequisites**:
    - Python 3.8+
    - An RPC URL for a source chain (e.g., Sepolia testnet from Infura/Alchemy).
    - An RPC URL for a destination chain (e.g., Polygon Mumbai testnet).

2.  **Setup Environment**:

    *   Clone the repository.
    *   Create a virtual environment:
        ```bash
        python -m venv venv
        source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
        ```
    *   Install dependencies:
        ```bash
        pip install -r requirements.txt
        ```
    *   Create a `.env` file in the root directory. This is the recommended way to manage your secrets and configuration. Populate it with your details. (The script uses default public RPCs and dummy addresses if these are not set).

        ```dotenv
        # .env file
        
        # Source Chain (e.g., Sepolia)
        SOURCE_CHAIN_RPC_URL="https://sepolia.infura.io/v3/YOUR_INFURA_PROJECT_ID"
        SOURCE_BRIDGE_CONTRACT_ADDRESS="0x..._your_bridge_contract_on_sepolia"
        
        # Destination Chain (e.g., Polygon Mumbai)
        DESTINATION_CHAIN_RPC_URL="https://polygon-mumbai.g.alchemy.com/v2/YOUR_ALCHEMY_KEY"
        DESTINATION_CHAIN_ID=80001
        DESTINATION_BRIDGE_CONTRACT_ADDRESS="0x..._your_bridge_contract_on_mumbai"
        
        # Relayer's Wallet (must have funds on the destination chain for gas)
        # IMPORTANT: This is a secret. Do not share it.
        RELAYER_PRIVATE_KEY="0x_your_private_key_for_signing_transactions"
        ```

3.  **Run the Listener**:

    Execute the script from your terminal:

    ```bash
    python script.py
    ```

4.  **Observe the Output**:

    The script will start logging its activity to the console. You will see messages about connecting to the chains, scanning block ranges, and any events it finds and processes.

    ```
    2023-10-27 15:30:00 - INFO - Successfully connected to RPC endpoint: https://rpc.sepolia.org
    2023-10-27 15:30:01 - INFO - Successfully connected to RPC endpoint: https://rpc-mumbai.maticvigil.com
    2023-10-27 15:30:01 - INFO - Loaded 52 processed transaction hashes from processed_transactions_state.json
    2023-10-27 15:30:01 - INFO - Starting cross-chain event listener...
    2023-10-27 15:30:01 - INFO - Listening for 'CrossChainTransferInitiated' events on contract 0x12345...
    2023-10-27 15:30:01 - INFO - Starting poll from block: 4501234
    2023-10-27 15:30:01 - INFO - Waiting for new blocks to be confirmed. Current head: 4501237
    ...
    2023-10-27 15:30:16 - INFO - Scanning blocks from 4501235 to 4501237...
    2023-10-27 15:30:18 - INFO - Found 1 new event(s).
    2023-10-27 15:30:18 - INFO - New valid event detected in transaction: 0xabc...def
    2023-10-27 15:30:18 - INFO - Processing event: Recipient=0x..., Amount=100000000, Nonce=42
    2023-10-27 15:30:19 - INFO - [SIMULATION] Would send transaction to release 100000000 tokens to 0x... on chain 80001.
    2023-10-27 15:30:19 - INFO - [SIMULATION] Signed Transaction: 0xf86...
    ```

