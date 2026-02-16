"""Payment Service — handles crypto settlement via Coinbase AgentKit.

For MVP: Provides both a real AgentKit integration and a simulated mode
for testing without real blockchain transactions.

In simulation mode, generates fake transaction hashes.
In production mode, uses CdpEvmWalletProvider for Base Sepolia USDC transfers.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from agentic_clearinghouse.config import get_settings
from agentic_clearinghouse.logging_config import get_logger

if TYPE_CHECKING:
    from decimal import Decimal

logger = get_logger(__name__)


class PaymentService:
    """Handles escrow funding and settlement payments."""

    def __init__(self, simulate: bool = True) -> None:
        """Initialize payment service.

        Args:
            simulate: If True, generate fake tx hashes instead of real on-chain txs.
                     Set to False for real Base Sepolia transactions.
        """
        self._simulate = simulate

    async def create_escrow_wallet(self) -> str:
        """Create or return an escrow wallet address.

        In simulation mode, returns a deterministic fake address.
        In production, creates a new CDP wallet.
        """
        if self._simulate:
            fake_addr = "0x" + uuid.uuid4().hex[:40]
            logger.info("payment.escrow_wallet_created", address=fake_addr, simulated=True)
            return fake_addr

        # Real implementation with AgentKit
        settings = get_settings()
        try:
            from coinbase_agentkit import CdpEvmWalletProvider, CdpEvmWalletProviderConfig

            wallet_provider = CdpEvmWalletProvider(CdpEvmWalletProviderConfig(
                api_key_id=settings.cdp_api_key_id,
                api_key_secret=settings.cdp_api_key_secret,
                wallet_secret=settings.cdp_wallet_secret,
                network_id=settings.cdp_network_id,
            ))
            address = wallet_provider.get_address()
            logger.info("payment.escrow_wallet_created", address=address, simulated=False)
            return address
        except Exception as exc:
            logger.error("payment.wallet_creation_failed", error=str(exc))
            raise

    async def simulate_funding(
        self,
        escrow_wallet: str,
        amount_usdc: Decimal,
        buyer_wallet: str,
    ) -> str:
        """Simulate an on-chain funding transaction.

        Returns a fake or real transaction hash.
        """
        if self._simulate:
            tx_hash = "0x" + uuid.uuid4().hex + uuid.uuid4().hex[:2]
            logger.info(
                "payment.funding_simulated",
                tx_hash=tx_hash,
                amount=str(amount_usdc),
                from_wallet=buyer_wallet,
                to_wallet=escrow_wallet,
            )
            return tx_hash

        # Real implementation would check on-chain balance
        raise NotImplementedError("Real funding verification not yet implemented")

    async def transfer_to_worker(
        self,
        worker_wallet: str,
        amount_usdc: Decimal,
        escrow_wallet: str,
    ) -> str:
        """Transfer USDC from escrow to worker wallet.

        Returns the settlement transaction hash.
        """
        if self._simulate:
            tx_hash = "0x" + uuid.uuid4().hex + uuid.uuid4().hex[:2]
            logger.info(
                "payment.settlement_simulated",
                tx_hash=tx_hash,
                amount=str(amount_usdc),
                from_wallet=escrow_wallet,
                to_wallet=worker_wallet,
            )
            return tx_hash

        # Real implementation with AgentKit ERC-20 transfer
        settings = get_settings()
        try:
            from coinbase_agentkit import (
                AgentKit,
                AgentKitConfig,
                CdpEvmWalletProvider,
                CdpEvmWalletProviderConfig,
                erc20_action_provider,
                wallet_action_provider,
            )

            wallet_provider = CdpEvmWalletProvider(CdpEvmWalletProviderConfig(
                api_key_id=settings.cdp_api_key_id,
                api_key_secret=settings.cdp_api_key_secret,
                wallet_secret=settings.cdp_wallet_secret,
                network_id=settings.cdp_network_id,
                address=escrow_wallet,
            ))

            AgentKit(AgentKitConfig(
                wallet_provider=wallet_provider,
                action_providers=[
                    erc20_action_provider(),
                    wallet_action_provider(),
                ],
            ))

            # Execute ERC-20 USDC transfer
            # USDC on Base Sepolia: 0x036CbD53842c5426634e7929541eC2318f3dCF7e
            result = erc20_action_provider().transfer(
                wallet_provider,
                {
                    "to": worker_wallet,
                    "amount": str(amount_usdc),
                    "contract_address": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
                },
            )

            logger.info("payment.settlement_complete", result=result)
            return result  # Contains tx hash

        except Exception as exc:
            logger.error("payment.settlement_failed", error=str(exc))
            raise
