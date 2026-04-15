/**
 * Web3PaymentGate.tsx
 *
 * Browser-native crypto payment modal. Triggered when the user wants to wager
 * more $V than their current balance, or after a SYSTEM_LOCK prompts topup.
 *
 * SUPPORTED WALLETS
 * ─────────────────
 *   EVM   → MetaMask (window.ethereum), Coinbase Wallet, WalletConnect
 *   Solana → Phantom (window.solana), Backpack, Solflare
 *
 * FLOW
 * ────
 *   1. User selects chain + amount → POST /billing/web3/intent
 *   2. Gateway returns { platform_address, amount_token, token_contract, memo }
 *   3. User approves tx in wallet → tx_hash returned
 *   4. POST /billing/web3/confirm { intent_id, tx_hash, chain }
 *   5. Poll GET /billing/web3/status/:intent_id until status === "confirmed"
 *   6. onSuccess(amountV) fires — parent updates balance in Zustand/store
 *
 * USDC TRANSFER (EVM)
 * ───────────────────
 *   Uses eth_sendTransaction with ERC-20 transfer() calldata.
 *   Encodes: transfer(address recipient, uint256 amount)
 *   USDC decimals = 6 → multiply USD amount by 1_000_000
 *
 * SOL/USDC TRANSFER (Solana)
 * ──────────────────────────
 *   Uses window.solana.request({ method: "signAndSendTransaction", ... })
 *   with a SPL Token transfer instruction.
 *   Falls back to lamport transfer for SOL (no token program needed).
 *
 * PACKAGES REQUIRED (add to web/package.json)
 * ──────────────────────────────────────────
 *   ethers ^6.x   (EVM encoding only — no provider, uses window.ethereum directly)
 */

'use client';

import React, { useState, useCallback } from 'react';

const API_BASE = process.env['NEXT_PUBLIC_API_URL'] ?? 'https://app.openvegas.ai';

// ─── Type declarations for wallet globals ────────────────────────────────────

interface EthereumProvider {
  request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
  isMetaMask?: boolean;
}

interface SolanaProvider {
  isPhantom?: boolean;
  publicKey?: { toBase58(): string };
  request: (args: { method: string; params?: unknown }) => Promise<unknown>;
  signAndSendTransaction: (tx: unknown) => Promise<{ signature: string }>;
}

declare global {
  interface Window {
    ethereum?: EthereumProvider;
    solana?:   SolanaProvider;
  }
}

// ─── Wallet detection ─────────────────────────────────────────────────────────

export function detectWallets(): { evm: boolean; solana: boolean } {
  if (typeof window === 'undefined') return { evm: false, solana: false };
  return {
    evm:    Boolean(window.ethereum),
    solana: Boolean(window.solana?.isPhantom),
  };
}

// ─── ERC-20 transfer calldata ────────────────────────────────────────────────

function encodeERC20Transfer(to: string, amountUsdc: number): string {
  // transfer(address,uint256) selector = 0xa9059cbb
  const selector = 'a9059cbb';
  // address padded to 32 bytes
  const paddedTo = to.toLowerCase().replace('0x', '').padStart(64, '0');
  // USDC has 6 decimals
  const amountRaw = BigInt(Math.round(amountUsdc * 1_000_000));
  const paddedAmount = amountRaw.toString(16).padStart(64, '0');
  return `0x${selector}${paddedTo}${paddedAmount}`;
}

// ─── EVM payment ─────────────────────────────────────────────────────────────

async function sendEvmPayment(
  platformAddress: string,
  tokenContract:   string | null,
  amountUsd:       number,
  currency:        'USDC' | 'ETH',
): Promise<string> {
  const eth = window.ethereum;
  if (!eth) throw new Error('No Ethereum wallet detected. Install MetaMask.');

  // Request account access
  const accounts = await eth.request({ method: 'eth_requestAccounts' }) as string[];
  const from = accounts[0];
  if (!from) throw new Error('No account selected in wallet');

  let txHash: string;

  if (currency === 'USDC' && tokenContract) {
    // ERC-20 USDC transfer
    const calldata = encodeERC20Transfer(platformAddress, amountUsd);
    txHash = await eth.request({
      method: 'eth_sendTransaction',
      params: [{
        from,
        to:   tokenContract,
        data: calldata,
        // Let wallet estimate gas
      }],
    }) as string;
  } else {
    // ETH transfer (fallback)
    const weiAmount = BigInt(Math.round(amountUsd * 1e18));
    txHash = await eth.request({
      method: 'eth_sendTransaction',
      params: [{
        from,
        to:    platformAddress,
        value: '0x' + weiAmount.toString(16),
      }],
    }) as string;
  }

  return txHash;
}

// ─── Solana payment ───────────────────────────────────────────────────────────

async function sendSolanaPayment(
  platformAddress: string,
  amountUsd:       number,
  currency:        'USDC' | 'SOL',
  intentMemo:      string,
): Promise<string> {
  const solana = window.solana;
  if (!solana) throw new Error('No Solana wallet detected. Install Phantom.');

  if (!solana.publicKey) {
    await solana.request({ method: 'connect' });
  }
  if (!solana.publicKey) throw new Error('Wallet not connected');

  if (currency === 'SOL') {
    // SOL transfer via system program
    // Use @solana/web3.js dynamically to avoid bundling it in non-Solana paths
    const { Connection, PublicKey, SystemProgram, Transaction, LAMPORTS_PER_SOL } =
      await import('@solana/web3.js');
    const rpc = process.env['NEXT_PUBLIC_SOLANA_RPC'] ?? 'https://api.mainnet-beta.solana.com';
    const connection = new Connection(rpc, 'confirmed');
    const { blockhash } = await connection.getLatestBlockhash();

    const tx = new Transaction({ recentBlockhash: blockhash, feePayer: solana.publicKey });
    tx.add(SystemProgram.transfer({
      fromPubkey: solana.publicKey,
      toPubkey:   new PublicKey(platformAddress),
      lamports:   Math.round(amountUsd * LAMPORTS_PER_SOL),
    }));

    const { signature } = await solana.signAndSendTransaction(tx);
    return signature;
  }

  // USDC on Solana — use @solana/spl-token + memo
  const { Connection, PublicKey, Transaction } = await import('@solana/web3.js');
  const { getAssociatedTokenAddress, createTransferInstruction } =
    await import('@solana/spl-token');

  const USDC_MINT_MAINNET = new PublicKey(
    process.env['NEXT_PUBLIC_SOLANA_USDC_MINT'] ?? 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
  );
  const rpc = process.env['NEXT_PUBLIC_SOLANA_RPC'] ?? 'https://api.mainnet-beta.solana.com';
  const connection = new Connection(rpc, 'confirmed');
  const { blockhash } = await connection.getLatestBlockhash();

  const senderAta   = await getAssociatedTokenAddress(USDC_MINT_MAINNET, solana.publicKey);
  const platformKey = new PublicKey(platformAddress);
  const receiverAta = await getAssociatedTokenAddress(USDC_MINT_MAINNET, platformKey);

  const amountTokenUnits = Math.round(amountUsd * 1_000_000);  // USDC = 6 decimals

  const tx = new Transaction({ recentBlockhash: blockhash, feePayer: solana.publicKey });
  tx.add(createTransferInstruction(senderAta, receiverAta, solana.publicKey, amountTokenUnits));

  const { signature } = await solana.signAndSendTransaction(tx);
  return signature;
}

// ─── Component ────────────────────────────────────────────────────────────────

type Chain = 'evm' | 'solana';
type Currency = 'USDC' | 'ETH' | 'SOL';

interface Web3PaymentGateProps {
  token:        string;       // Supabase JWT
  defaultAmount?: number;     // USD
  onSuccess?:   (amountV: number) => void;
  onCancel?:    () => void;
}

const PRESET_AMOUNTS = [5, 25, 100, 500];
const USD_TO_V = 100;

export function Web3PaymentGate({
  token,
  defaultAmount = 25,
  onSuccess,
  onCancel,
}: Web3PaymentGateProps) {
  const wallets = detectWallets();

  const [chain,      setChain]      = useState<Chain>(wallets.evm ? 'evm' : 'solana');
  const [currency,   setCurrency]   = useState<Currency>('USDC');
  const [amountUsd,  setAmountUsd]  = useState(defaultAmount);
  const [step,       setStep]       = useState<'idle' | 'waiting_wallet' | 'confirming' | 'done' | 'error'>('idle');
  const [errorMsg,   setErrorMsg]   = useState('');
  const [intentId,   setIntentId]   = useState('');
  const [txHash,     setTxHash]     = useState('');

  const handlePay = useCallback(async () => {
    setStep('waiting_wallet');
    setErrorMsg('');

    try {
      // Step 1: Create payment intent
      const intentRes = await fetch(`${API_BASE}/billing/web3/intent`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body:    JSON.stringify({ chain, currency, amount_usd: amountUsd.toFixed(2) }),
      });
      if (!intentRes.ok) {
        const err = await intentRes.json().catch(() => ({})) as { detail?: string };
        throw new Error(err.detail ?? 'Failed to create payment intent');
      }
      const intent = await intentRes.json() as {
        intent_id: string;
        platform_address: string;
        token_contract: string | null;
        memo: string;
      };
      setIntentId(intent.intent_id);

      // Step 2: Submit wallet transaction
      let hash: string;
      if (chain === 'evm') {
        hash = await sendEvmPayment(intent.platform_address, intent.token_contract, amountUsd, currency as 'USDC' | 'ETH');
      } else {
        hash = await sendSolanaPayment(intent.platform_address, amountUsd, currency as 'USDC' | 'SOL', intent.memo);
      }
      setTxHash(hash);
      setStep('confirming');

      // Step 3: Notify backend
      await fetch(`${API_BASE}/billing/web3/confirm`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body:    JSON.stringify({ intent_id: intent.intent_id, tx_hash: hash, chain }),
      });

      // Step 4: Poll for confirmation (up to 3 minutes)
      let attempts = 0;
      while (attempts < 36) {
        await new Promise(r => setTimeout(r, 5_000));
        const statusRes = await fetch(`${API_BASE}/billing/web3/status/${intent.intent_id}`, {
          headers: { 'Authorization': `Bearer ${token}` },
        });
        if (statusRes.ok) {
          const s = await statusRes.json() as { status: string; amount_v?: number };
          if (s.status === 'confirmed') {
            setStep('done');
            onSuccess?.(s.amount_v ?? amountUsd * USD_TO_V);
            return;
          }
          if (s.status === 'failed') throw new Error('Transaction failed on-chain');
        }
        attempts++;
      }
      throw new Error('Confirmation timed out. Check your wallet and try again.');
    } catch (err) {
      setErrorMsg((err as Error).message);
      setStep('error');
    }
  }, [chain, currency, amountUsd, token, onSuccess]);

  // ── Styles ─────────────────────────────────────────────────────────────────
  const overlayStyle: React.CSSProperties = {
    position:   'fixed', inset: 0,
    background: 'rgba(0,0,0,0.9)', backdropFilter: 'blur(8px)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 100, fontFamily: 'monospace',
  };
  const boxStyle: React.CSSProperties = {
    background:  '#0a0a0a', border: '1px solid #00ff88',
    padding:     '2rem', width: '100%', maxWidth: 420,
    color:       '#e0e0e0',
  };
  const btnStyle = (active: boolean): React.CSSProperties => ({
    background:  active ? '#00ff88' : 'transparent',
    border:      '1px solid #00ff88',
    color:       active ? '#000' : '#00ff88',
    fontFamily:  'monospace',
    padding:     '0.3rem 0.8rem',
    cursor:      'pointer',
    fontSize:    '0.85rem',
  });

  return (
    <div style={overlayStyle}>
      <div style={boxStyle}>
        <div style={{ color: '#00ff88', fontWeight: 'bold', fontSize: '1.1rem', marginBottom: '1.5rem' }}>
          ▋ ADD FUNDS
        </div>

        {/* Chain selector */}
        <div style={{ marginBottom: '1rem' }}>
          <div style={{ color: '#555', fontSize: '0.75rem', marginBottom: '0.4rem' }}>NETWORK</div>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {wallets.evm    && <button style={btnStyle(chain==='evm')}    onClick={() => { setChain('evm');    setCurrency('USDC'); }}>EVM (ETH/USDC)</button>}
            {wallets.solana && <button style={btnStyle(chain==='solana')} onClick={() => { setChain('solana'); setCurrency('USDC'); }}>Solana</button>}
            {!wallets.evm && !wallets.solana && (
              <div style={{ color: '#ff4444', fontSize: '0.85rem' }}>
                No wallet detected. Install MetaMask or Phantom.
              </div>
            )}
          </div>
        </div>

        {/* Currency selector */}
        {chain === 'evm' && (
          <div style={{ marginBottom: '1rem' }}>
            <div style={{ color: '#555', fontSize: '0.75rem', marginBottom: '0.4rem' }}>CURRENCY</div>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button style={btnStyle(currency==='USDC')} onClick={() => setCurrency('USDC')}>USDC</button>
              <button style={btnStyle(currency==='ETH')}  onClick={() => setCurrency('ETH')}>ETH</button>
            </div>
          </div>
        )}

        {/* Amount presets */}
        <div style={{ marginBottom: '1.5rem' }}>
          <div style={{ color: '#555', fontSize: '0.75rem', marginBottom: '0.4rem' }}>AMOUNT (USD)</div>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {PRESET_AMOUNTS.map(a => (
              <button key={a} style={btnStyle(amountUsd===a)} onClick={() => setAmountUsd(a)}>
                ${a}
              </button>
            ))}
          </div>
          <div style={{ marginTop: '0.5rem', color: '#888', fontSize: '0.75rem' }}>
            = {(amountUsd * USD_TO_V).toLocaleString()} $V
          </div>
        </div>

        {/* Status display */}
        {step === 'confirming' && (
          <div style={{ color: '#ffff44', marginBottom: '1rem', fontSize: '0.85rem' }}>
            Waiting for {chain === 'evm' ? '3 EVM' : '1 Solana'} confirmation(s)...
            <br/><span style={{ color: '#555', fontSize: '0.7rem' }}>{txHash.slice(0, 20)}...</span>
          </div>
        )}
        {step === 'done' && (
          <div style={{ color: '#00ff88', marginBottom: '1rem' }}>
            ✓ {(amountUsd * USD_TO_V).toLocaleString()} $V added to your wallet
          </div>
        )}
        {step === 'error' && (
          <div style={{ color: '#ff4444', marginBottom: '1rem', fontSize: '0.85rem' }}>
            {errorMsg}
          </div>
        )}

        {/* Action buttons */}
        <div style={{ display: 'flex', gap: '1rem' }}>
          {step !== 'done' && (wallets.evm || wallets.solana) && (
            <button
              onClick={handlePay}
              disabled={step === 'waiting_wallet' || step === 'confirming'}
              style={{
                ...btnStyle(true),
                padding: '0.6rem 1.5rem',
                opacity: (step === 'waiting_wallet' || step === 'confirming') ? 0.5 : 1,
              }}
            >
              {step === 'waiting_wallet' ? 'WAITING FOR WALLET...'
               : step === 'confirming'   ? 'CONFIRMING...'
               : `PAY $${amountUsd} →`}
            </button>
          )}
          <button
            onClick={step === 'done' ? onCancel : onCancel}
            style={{ ...btnStyle(false), padding: '0.6rem 1rem' }}
          >
            {step === 'done' ? 'CLOSE' : 'CANCEL'}
          </button>
        </div>
      </div>
    </div>
  );
}
