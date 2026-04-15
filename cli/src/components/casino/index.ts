/**
 * casino/index.ts — barrel export
 *
 * Usage in ChatScreen.tsx:
 *   import {
 *     PachinkoBoard, SlotSpinner, CrashCompiler, FlexReceipt, GlobalTicker,
 *     ExitModal, MicroAdvanceModal, RakebackClaim, ProvablyFairReceipt,
 *   } from '@/components/casino';
 */

export { PachinkoBoard }   from './PachinkoBoard';
export { SlotSpinner }     from './SlotSpinner';
export { CrashCompiler }   from './CrashCompiler';
export { FlexReceipt, buildReceiptText } from './FlexReceipt';
export { GlobalTicker }    from './GlobalTicker';
export { ExitModal }       from './ExitModal';
export { MicroAdvanceModal } from './MicroAdvanceModal';
export { RakebackClaim }   from './RakebackClaim';
export { ProvablyFairReceipt } from './ProvablyFairReceipt';
export type { VerifyData, ProvablyFairReceiptProps } from './ProvablyFairReceipt';
