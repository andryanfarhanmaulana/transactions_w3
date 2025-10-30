import os
import json
import time
import logging
from typing import Dict, Any, Optional, List

from web3 import Web3
from web3.contract import Contract
from web3.middleware import geth_poa_middleware
from web3.types import TxReceipt, LogReceipt
from hexbytes import HexBytes

# Configure logging for clear output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


class Config:
    """Configuration class to hold all necessary parameters."""
    # --- Source Chain Configuration ---
    SOURCE_CHAIN_RPC_URL: str = os.getenv('SOURCE_CHAIN_RPC_URL', 'https://rpc.sepolia.org')
    SOURCE_CHAIN_ID: int = int(os.getenv('SOURCE_CHAIN_ID', 11155111))
    # This is a placeholder address for a bridge contract on the source chain
    SOURCE_BRIDGE_CONTRACT_ADDRESS: str = os.getenv('SOURCE_BRIDGE_CONTRACT_ADDRESS', '0x1234567890123456789012345678901234567890')

    # --- Destination Chain Configuration ---
    DESTINATION_CHAIN_RPC_URL: str = os.getenv('DESTINATION_CHAIN_RPC_URL', 'https://rpc-mumbai.maticvigil.com')
    DESTINATION_CHAIN_ID: int = int(os.getenv('DESTINATION_CHAIN_ID', 80001))
    # This is a placeholder address for a bridge contract on the destination chain
    DESTINATION_BRIDGE_CONTRACT_ADDRESS: str = os.getenv('DESTINATION_BRIDGE_CONTRACT_ADDRESS', '0x0987654321098765432109876543210987654321')

    # --- Relayer (Listener) Wallet Configuration ---
    # IMPORTANT: Never commit private keys to version control. Use environment variables.
    RELAYER_PRIVATE_KEY: str = os.getenv('RELAYER_PRIVATE_KEY', '0x' + 'a' * 64) # Dummy key for safety

    # --- Listener Configuration ---
    POLLING_INTERVAL_SECONDS: int = 15
    STATE_FILE_PATH: str = 'processed_transactions_state.json'
    CONFIRMATION_BLOCKS: int = 5 # Number of blocks to wait for finality

    # --- Contract ABIs (simplified for demonstration) ---
    SOURCE_BRIDGE_ABI: List[Dict] = json.loads('''
    [
        {
            "anonymous": false,
            "inputs": [
                {"indexed": true, "internalType": "address", "name": "sender", "type": "address"},
                {"indexed": true, "internalType": "address", "name": "recipient", "type": "address"},
                {"indexed": false, "internalType": "uint256", "name": "amount", "type": "uint256"},
                {"indexed": false, "internalType": "uint256", "name": "destinationChainId", "type": "uint256"},
                {"indexed": true, "internalType": "uint256", "name": "nonce", "type": "uint256"}
            ],
            "name": "CrossChainTransferInitiated",
            "type": "event"
        }
    ]
    ''')

    DESTINATION_BRIDGE_ABI: List[Dict] = json.loads('''
    [
        {
            "inputs": [
                {"internalType": "address", "name": "recipient", "type": "address"},
                {"internalType": "uint256", "name": "amount", "type": "uint256"},
                {"internalType": "uint256", "name": "sourceNonce", "type": "uint256"}
            ],
            "name": "releaseTokens",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function"
        }
    ]
    ''')


class BlockchainConnector:
    """Handles connection to a blockchain node via Web3.py."""

    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url
        self.w3: Optional[Web3] = None
        self.connect()

    def connect(self) -> None:
        """Establishes a connection to the RPC endpoint."""
        try:
            self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            # Inject Proof of Authority middleware for chains like Polygon, Goerli, Sepolia
            self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
            if not self.w3.is_connected():
                raise ConnectionError(f"Failed to connect to {self.rpc_url}")
            logging.info(f"Successfully connected to RPC endpoint: {self.rpc_url}")
        except Exception as e:
            logging.error(f"Error connecting to {self.rpc_url}: {e}")
            self.w3 = None

    def get_w3(self) -> Web3:
        """Returns the Web3 instance, raises error if not connected."""
        if not self.w3 or not self.w3.is_connected():
            logging.warning("Web3 not connected. Attempting to reconnect...")
            self.connect()
            if not self.w3:
                raise ConnectionError("Unable to establish a Web3 connection.")
        return self.w3


class StateManager:
    """Manages the state of processed transactions to prevent duplicates."""

    def __init__(self, state_file: str):
        self.state_file = state_file
        self.processed_txs: set = self._load_state()

    def _load_state(self) -> set:
        """Loads the set of processed transaction hashes from a file."""
        try:
            with open(self.state_file, 'r') as f:
                txs = set(json.load(f))
                logging.info(f"Loaded {len(txs)} processed transaction hashes from {self.state_file}")
                return txs
        except FileNotFoundError:
            logging.warning(f"State file {self.state_file} not found. Starting with empty state.")
            return set()
        except json.JSONDecodeError:
            logging.error(f"Could not decode JSON from {self.state_file}. Starting fresh.")
            return set()

    def _save_state(self) -> None:
        """Saves the current set of processed transaction hashes to a file."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(list(self.processed_txs), f, indent=4)
        except IOError as e:
            logging.error(f"Could not write to state file {self.state_file}: {e}")

    def is_processed(self, tx_hash: HexBytes) -> bool:
        """Checks if a transaction has already been processed."""
        return tx_hash.hex() in self.processed_txs

    def mark_as_processed(self, tx_hash: HexBytes) -> None:
        """Marks a transaction as processed and saves the state."""
        self.processed_txs.add(tx_hash.hex())
        self._save_state()


class TransactionProcessor:
    """Processes detected events and submits transactions to the destination chain."""

    def __init__(self, w3_dest: Web3, contract_dest: Contract, relayer_key: str, chain_id: int):
        self.w3 = w3_dest
        self.contract = contract_dest
        self.relayer_account = self.w3.eth.account.from_key(relayer_key)
        self.chain_id = chain_id

    def process_event(self, event: LogReceipt) -> None:
        """
        Validates an event and submits a corresponding transaction to the destination chain.
        This is a simulation and does not send a real transaction unless configured with a real key and gas.
        """
        try:
            event_args = event['args']
            recipient = event_args['recipient']
            amount = event_args['amount']
            nonce = event_args['nonce']

            logging.info(f"Processing event: Recipient={recipient}, Amount={amount}, Nonce={nonce}")

            # Build the transaction to call `releaseTokens` on the destination bridge contract
            tx_params = {
                'from': self.relayer_account.address,
                'to': self.contract.address,
                'nonce': self.w3.eth.get_transaction_count(self.relayer_account.address),
                'gas': 200000, # This should be estimated properly in a real scenario
                'gasPrice': self.w3.eth.gas_price, # Or use EIP-1559 fields
                'chainId': self.chain_id
            }

            # Get the function call data
            tx_data = self.contract.functions.releaseTokens(recipient, amount, nonce).build_transaction(tx_params)

            # Sign the transaction
            signed_tx = self.w3.eth.account.sign_transaction(tx_data, self.relayer_account.key)

            # --- DANGER ZONE --- #
            # The following line would send the transaction. In this simulation, we will just log it.
            # In a real-world scenario, you would uncomment this and handle potential reverts.
            # tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            # receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
            # logging.info(f"Successfully sent release transaction to destination chain. TxHash: {receipt.transactionHash.hex()}")
            
            logging.info(f"[SIMULATION] Would send transaction to release {amount} tokens to {recipient} on chain {self.chain_id}.")
            logging.info(f"[SIMULATION] Signed Transaction: {signed_tx.rawTransaction.hex()}")

        except Exception as e:
            logging.error(f"Failed to process event from tx {event['transactionHash'].hex()}: {e}")


class BridgeEventListener:
    """
    The main orchestrator. Listens for events on the source chain 
    and triggers the processing on the destination chain.
    """

    def __init__(self, config: Config):
        self.config = config
        self.state_manager = StateManager(config.STATE_FILE_PATH)

        # Setup source chain connection
        self.source_connector = BlockchainConnector(config.SOURCE_CHAIN_RPC_URL)
        self.w3_source = self.source_connector.get_w3()
        self.source_contract: Contract = self.w3_source.eth.contract(
            address=Web3.to_checksum_address(config.SOURCE_BRIDGE_CONTRACT_ADDRESS),
            abi=config.SOURCE_BRIDGE_ABI
        )

        # Setup destination chain connection and processor
        self.dest_connector = BlockchainConnector(config.DESTINATION_CHAIN_RPC_URL)
        self.w3_dest = self.dest_connector.get_w3()
        dest_contract: Contract = self.w3_dest.eth.contract(
            address=Web3.to_checksum_address(config.DESTINATION_BRIDGE_CONTRACT_ADDRESS),
            abi=config.DESTINATION_BRIDGE_ABI
        )
        self.tx_processor = TransactionProcessor(
            w3_dest=self.w3_dest,
            contract_dest=dest_contract,
            relayer_key=config.RELAYER_PRIVATE_KEY,
            chain_id=config.DESTINATION_CHAIN_ID
        )

    def listen(self):
        """Main event listening loop."""
        logging.info("Starting cross-chain event listener...")
        logging.info(f"Listening for 'CrossChainTransferInitiated' events on contract {self.config.SOURCE_BRIDGE_CONTRACT_ADDRESS}")
        
        try:
            # Start polling from the latest block to avoid processing a long history on startup.
            # In a production system, you'd persist the last polled block number.
            last_polled_block = self.w3_source.eth.block_number
            logging.info(f"Starting poll from block: {last_polled_block}")

            while True:
                try:
                    latest_block = self.w3_source.eth.block_number
                    # We poll up to a block with a certain number of confirmations
                    to_block = latest_block - self.config.CONFIRMATION_BLOCKS

                    if to_block > last_polled_block:
                        logging.info(f"Scanning blocks from {last_polled_block + 1} to {to_block}...")

                        # Create a filter for the event we are interested in
                        event_filter = self.source_contract.events.CrossChainTransferInitiated.create_filter(
                            fromBlock=last_polled_block + 1,
                            toBlock=to_block
                        )
                        events = event_filter.get_all_entries()

                        if events:
                            self._handle_events(events)
                        else:
                            logging.info("No new events found.")

                        last_polled_block = to_block
                    else:
                        logging.info(f"Waiting for new blocks to be confirmed. Current head: {latest_block}")

                except Exception as e:
                    logging.error(f"An error occurred in the polling loop: {e}")
                    # Attempt to reconnect if connection is the issue
                    self.source_connector.connect()
                    self.w3_source = self.source_connector.get_w3()

                time.sleep(self.config.POLLING_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logging.info("Shutting down listener...")
        finally:
            logging.info("Listener has been shut down.")

    def _handle_events(self, events: List[LogReceipt]):
        """Helper function to process a list of detected events."""
        logging.info(f"Found {len(events)} new event(s).")
        for event in events:
            tx_hash = event['transactionHash']
            
            # First, check if the event's target chain ID matches our destination chain
            if event['args']['destinationChainId'] != self.config.DESTINATION_CHAIN_ID:
                logging.warning(f"Skipping event for different chain ID {event['args']['destinationChainId']} in tx {tx_hash.hex()}.")
                continue

            # Second, check if we have already processed this transaction
            if self.state_manager.is_processed(tx_hash):
                logging.warning(f"Skipping already processed transaction: {tx_hash.hex()}")
                continue

            logging.info(f"New valid event detected in transaction: {tx_hash.hex()}")
            self.tx_processor.process_event(event)
            self.state_manager.mark_as_processed(tx_hash)


if __name__ == "__main__":
    # For real usage, you would use a .env file to load these variables
    # from dotenv import load_dotenv
    # load_dotenv()

    # Validate that a non-dummy private key is set for a real run
    if Config.RELAYER_PRIVATE_KEY == '0x' + 'a' * 64:
        logging.warning("Using a DUMMY private key. No transactions will be sent.")
        logging.warning("Set RELAYER_PRIVATE_KEY environment variable to run for real.")

    try:
        listener = BridgeEventListener(Config())
        listener.listen()
    except ConnectionError as e:
        logging.critical(f"Could not establish initial blockchain connection: {e}")
    except Exception as e:
        logging.critical(f"A critical error occurred: {e}", exc_info=True)

# @-internal-utility-start
def validate_payload_3912(payload: dict):
    """Validates incoming data payload on 2025-10-30 12:45:48"""
    if not isinstance(payload, dict):
        return False
    required_keys = ['id', 'timestamp', 'data']
    return all(key in payload for key in required_keys)
# @-internal-utility-end


# @-internal-utility-start
def get_config_value_6786(key: str):
    """Reads a value from a simple key-value config. Added on 2025-10-30 12:46:28"""
    with open('config.ini', 'r') as f:
        for line in f:
            if line.startswith(key):
                return line.split('=')[1].strip()
    return None
# @-internal-utility-end

