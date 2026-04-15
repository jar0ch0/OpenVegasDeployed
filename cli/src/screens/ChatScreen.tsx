/**
 * ChatScreen.tsx
 *
 * Primary screen. Implements the split-pane layout:
 *
 *   NOT streaming:
 *   ┌──────────────────────── full terminal width ─────────────────────────┐
 *   │  [user]  › prompt text                                               │
 *   │  [ai]      response text (wrapped)                                   │
 *   │  [user]  › next prompt                                               │
 *   │  [ai]      streaming...                                              │
 *   │  ────────────────────────────────────────────────────────────────── │
 *   │  › input cursor▌                                                     │
 *   └──────────────────────────────────────────────────────────────────────┘
 *
 *   STREAMING (showCasino = true):
 *   ┌──────────── full terminal width ────────────────────────────────────┐
 *   │  INFERENCE STREAM (left 60%)  │  PACHINKO (right 40%)              │
 *   │  ...token-by-token output...  │  ·+·+·+·+·+·                       │
 *   │                               │      O   (ball)                     │
 *   │                               │  ┌───┬──┬──┬──┬──┐                │
 *   │                               │  │1x │2x│5x│10│..│                │
 *   └───────────────────────────────┴──┴───┴──┴──┴──┴──┘────────────────┘
 *
 *   STREAMING (showCasino = false):
 *   Same as NOT streaming layout but stream.buffer is shown live in place
 *   of a completed message, and the input line is hidden.
 *
 * ZUSTAND READS
 *   stream.buffer         → live SSE accumulation (shown in left panel)
 *   stream.isStreaming     → triggers PachinkoBoard mount + hides input
 *   chat.currentRunId     → used as PachinkoBoard seed
 *   session.jwt           → auth header for inference calls
 *   ui.isExiting          → blocks input handling while exit modal is open
 *   ui.needsMicroAdvance  → blocks input handling while advance modal is open
 */

import React, {
  useState,
  useCallback,
  useEffect,
  useRef,
} from 'react';
import { Box, Text, useInput, useStdout } from 'ink';
import chalk from 'chalk';
import { useStore } from '../store/index.js';
import { PachinkoBoard } from '../components/casino/PachinkoBoard.js';

// ─── Types ────────────────────────────────────────────────────────────────────

interface Message {
  id:      string;
  role:    'user' | 'assistant';
  content: string;
}

export interface ChatScreenProps {
  apiBase:             string;
  initialPrompt?:      string;
  sessionId?:          string;
  showCasino:          boolean;
  /** App.tsx registers the submit fn so MicroAdvanceModal can re-trigger it. */
  onRegisterSubmit?:   (fn: (prompt: string) => void) => void;
}

// ─── SSE streaming helper ─────────────────────────────────────────────────────

async function streamInference(opts: {
  apiBase:    string;
  jwt:        string | null;
  prompt:     string;
  sessionId?: string;
  onChunk:    (text: string) => void;
  onDone:     () => void;
  onError:    (msg: string) => void;
  abortSignal: AbortSignal;
}): Promise<void> {
  const { apiBase, jwt, prompt, sessionId, onChunk, onDone, onError, abortSignal } = opts;

  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (jwt) headers['Authorization'] = `Bearer ${jwt}`;

  let res: Response;
  try {
    res = await fetch(`${apiBase}/inference/stream`, {
      method: 'POST',
      headers,
      body:   JSON.stringify({ prompt, thread_id: sessionId }),
      signal: abortSignal,
    });
  } catch (err) {
    if ((err as Error).name === 'AbortError') return;
    onError(`Network error: ${String(err)}`);
    return;
  }

  if (!res.ok) {
    const body = await res.text().catch(() => '');
    let detail = `Server error ${res.status}`;
    try { detail = (JSON.parse(body) as { detail?: string }).detail ?? detail; } catch {}
    onError(detail);
    return;
  }

  if (!res.body) { onError('Empty response body'); return; }

  const reader  = res.body.getReader();
  const decoder = new TextDecoder();
  let remainder = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      remainder += decoder.decode(value, { stream: true });
      const lines = remainder.split('\n');
      remainder = lines.pop() ?? '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6).trim();
        if (payload === '[DONE]') { onDone(); return; }
        try {
          const parsed = JSON.parse(payload) as {
            delta?: string;
            text?:  string;
            type?:  string;
          };
          if (parsed.type === 'text_delta' || parsed.delta || parsed.text) {
            onChunk(parsed.delta ?? parsed.text ?? '');
          }
        } catch {
          // Non-JSON SSE event — skip
        }
      }
    }
  } catch (err) {
    if ((err as Error).name !== 'AbortError') onError(String(err));
    return;
  }

  onDone();
}

// ─── InputLine ────────────────────────────────────────────────────────────────

function InputLine({ text }: { text: string }) {
  return (
    <Box borderStyle="single" borderColor="cyan" paddingLeft={1} paddingRight={1}>
      <Text color="cyan">›</Text>
      <Text> </Text>
      <Text>{text}</Text>
      <Text color="green">▌</Text>
    </Box>
  );
}

// ─── StatusLine ──────────────────────────────────────────────────────────────

function StatusLine({ isStreaming, error }: { isStreaming: boolean; error: string | null }) {
  if (error) {
    return (
      <Box paddingLeft={1}>
        <Text color="red">✗ {error}</Text>
      </Box>
    );
  }
  if (isStreaming) {
    return (
      <Box paddingLeft={1}>
        <Text color="yellow" dimColor>● streaming…</Text>
      </Box>
    );
  }
  return null;
}

// ─── HistoryView ──────────────────────────────────────────────────────────────

function HistoryView({
  messages,
  streamBuffer,
  isStreaming,
  termW,
  termRows,
}: {
  messages:    Message[];
  streamBuffer: string;
  isStreaming:  boolean;
  termW:        number;
  termRows:     number;
}) {
  // How many rows we can show: total rows minus input(3) minus status(1) minus padding(1)
  const visibleRows = Math.max(4, termRows - 5);

  // Expand each message into wrapped lines
  const allLines: Array<{ text: string; color: string }> = [];
  for (const msg of messages) {
    const prefix = msg.role === 'user' ? '› ' : '  ';
    const color  = msg.role === 'user' ? 'cyan' : 'white';
    const lines  = msg.content.split('\n');
    allLines.push({ text: prefix + (lines[0] ?? ''), color });
    for (let i = 1; i < lines.length; i++) {
      allLines.push({ text: '  ' + lines[i], color });
    }
  }

  if (isStreaming && streamBuffer) {
    const bufLines = streamBuffer.split('\n');
    allLines.push({ text: '  ' + (bufLines[0] ?? ''), color: 'green' });
    for (let i = 1; i < bufLines.length; i++) {
      allLines.push({ text: '  ' + bufLines[i], color: 'green' });
    }
  }

  const visible = allLines.slice(-visibleRows);

  return (
    <Box flexDirection="column" flexGrow={1} overflowY="hidden">
      {visible.length === 0 ? (
        <Box paddingLeft={2} paddingTop={1}>
          <Text dimColor>
            {chalk.dim('OpenVegas 0.4.0  ·  type a prompt and press Enter')}
          </Text>
        </Box>
      ) : (
        visible.map((line, i) => (
          <Text key={i} color={line.color} wrap="truncate">
            {line.text || ' '}
          </Text>
        ))
      )}
    </Box>
  );
}

// ─── ChatScreen ───────────────────────────────────────────────────────────────

export function ChatScreen({
  apiBase,
  initialPrompt,
  sessionId: externalSessionId,
  showCasino,
  onRegisterSubmit,
}: ChatScreenProps) {
  const { stdout }     = useStdout();
  const termW          = stdout?.columns ?? 100;
  const termRows       = (stdout as { rows?: number })?.rows ?? 30;

  // Store reads
  const jwt            = useStore((s) => s.session.jwt);
  const isStreaming    = useStore((s) => s.stream.isStreaming);
  const streamBuffer   = useStore((s) => s.stream.buffer);
  const currentRunId   = useStore((s) => s.chat.currentRunId);
  const isExiting      = useStore((s) => s.ui.isExiting);
  const needsAdvance   = useStore((s) => s.ui.needsMicroAdvance);

  // Store actions
  const appendBuffer       = useStore((s) => s.stream.appendBuffer);
  const setStreaming        = useStore((s) => s.stream.setStreaming);
  const clearBuffer        = useStore((s) => s.stream.clearBuffer);
  const setRunId           = useStore((s) => s.chat.setRunId);
  const recordLatency      = useStore((s) => s.casino.recordInferenceLatency);
  const setNeedsMicroAdv   = useStore((s) => s.ui.setNeedsMicroAdvance);

  // Local state
  const [inputText, setInputText]   = useState('');
  const [messages,  setMessages]    = useState<Message[]>([]);
  const [error,     setError]       = useState<string | null>(null);

  // Abort controller for in-flight SSE requests
  const abortRef    = useRef<AbortController | null>(null);
  const startMsRef  = useRef<number>(0);

  // ── Submit handler ─────────────────────────────────────────────────────────

  const handleSubmit = useCallback(async (prompt: string) => {
    if (!prompt.trim() || isStreaming) return;
    setError(null);

    const runId = `run_${Date.now().toString(36)}`;
    const userMsg: Message = {
      id:      `u_${runId}`,
      role:    'user',
      content: prompt.trim(),
    };

    setMessages((prev) => [...prev, userMsg]);
    clearBuffer();
    setStreaming(true);
    setRunId(runId);
    startMsRef.current = Date.now();

    // Cancel any previous request (should not be in flight, but defensive)
    abortRef.current?.abort();
    const abortCtrl = new AbortController();
    abortRef.current = abortCtrl;

    let accumulated = '';

    await streamInference({
      apiBase,
      jwt,
      prompt:      prompt.trim(),
      sessionId:   externalSessionId,
      abortSignal: abortCtrl.signal,
      onChunk: (text) => {
        accumulated += text;
        appendBuffer(text);
      },
      onDone: () => {
        const latency = Date.now() - startMsRef.current;
        recordLatency(latency);
        setStreaming(false);
        setRunId(null);

        const assistantMsg: Message = {
          id:      `a_${runId}`,
          role:    'assistant',
          content: accumulated || '(no response)',
        };
        setMessages((prev) => [...prev, assistantMsg]);
        clearBuffer();
        accumulated = '';
      },
      onError: (msg) => {
        setStreaming(false);
        setRunId(null);
        clearBuffer();

        // 402 = insufficient balance → trigger micro-advance modal
        if (msg.includes('402') || msg.toLowerCase().includes('insufficient')) {
          setNeedsMicroAdv(prompt.trim());
        } else {
          setError(msg);
        }
        accumulated = '';
      },
    });
  }, [
    isStreaming, jwt, apiBase, externalSessionId,
    appendBuffer, setStreaming, clearBuffer, setRunId,
    recordLatency, setNeedsMicroAdv,
  ]);

  // Register submit fn with App so MicroAdvanceModal can call it
  useEffect(() => {
    onRegisterSubmit?.(handleSubmit);
  }, [handleSubmit, onRegisterSubmit]);

  // Fire initial prompt once on mount
  const didInitRef = useRef(false);
  useEffect(() => {
    if (initialPrompt && !didInitRef.current) {
      didInitRef.current = true;
      void handleSubmit(initialPrompt);
    }
  }, [initialPrompt, handleSubmit]);

  // Cleanup in-flight request on unmount
  useEffect(() => {
    return () => { abortRef.current?.abort(); };
  }, []);

  // ── Keyboard input ────────────────────────────────────────────────────────

  useInput((input, key) => {
    // Yield to exit trap and modals while they are active
    if (isExiting || needsAdvance || isStreaming) return;

    if (key.return) {
      if (inputText.trim()) {
        const prompt = inputText.trim();
        setInputText('');
        void handleSubmit(prompt);
      }
      return;
    }

    if (key.backspace || key.delete) {
      setInputText((prev) => prev.slice(0, -1));
      return;
    }

    // Ignore modifier keys (ctrl/meta combos are handled by useExitTrap)
    if (key.ctrl || key.meta) return;

    if (input) {
      setInputText((prev) => prev + input);
    }
  });

  // ── Render ────────────────────────────────────────────────────────────────

  // During streaming with casino enabled: PachinkoBoard owns the full layout
  if (isStreaming && showCasino) {
    return <PachinkoBoard runId={currentRunId ?? 'default'} />;
  }

  // Otherwise: history + optional live buffer + input
  return (
    <Box flexDirection="column" width={termW}>
      <HistoryView
        messages={messages}
        streamBuffer={streamBuffer}
        isStreaming={isStreaming}
        termW={termW}
        termRows={termRows}
      />
      <StatusLine isStreaming={isStreaming} error={error} />
      {!isStreaming && <InputLine text={inputText} />}
    </Box>
  );
}
