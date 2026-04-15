/**
 * FileDropOverlay.tsx
 *
 * Drag-and-drop file attachment layer mounted over the web terminal.
 * Intercepts drop events, uploads to /ui/upload, then injects the file
 * reference into the active agent context via the WebSocket.
 *
 * LIMITS (from server env)
 * ────────────────────────
 *   OPENVEGAS_CHAT_MAX_ATTACHMENT_BYTES = 20_000_000  (20 MB)
 *   Allowed MIME types enforced server-side; client shows a pre-validation
 *   warning for obvious rejections (executables, archives > 20MB).
 *
 * UPLOAD FLOW
 * ───────────
 *   1. User drops file(s) onto the terminal
 *   2. Overlay renders a drop target with file list preview
 *   3. POST /ui/upload (multipart/form-data) → { file_id, filename, size_bytes }
 *   4. WebSocket message: { type: "input", data: "/attach <file_id> <filename>\n" }
 *      → The agent receives this as a regular user input line
 *      → The agent calls its fs_read tool with the file_id reference
 *
 * VISUAL
 * ──────
 *   While dragging over the window: full-screen neon border overlay
 *   After drop: file card with name, size, upload progress
 *   On success: auto-injects the attach command and clears the overlay
 */

'use client';

import React, { useState, useCallback, useRef, useEffect } from 'react';

const API_BASE     = process.env['NEXT_PUBLIC_API_URL'] ?? 'https://app.openvegas.ai';
const MAX_BYTES    = 20 * 1024 * 1024;  // 20 MB
const ALLOWED_MIME = new Set([
  'text/plain', 'text/markdown', 'text/csv',
  'application/json', 'application/xml',
  'application/pdf',
  'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml',
  'text/javascript', 'text/typescript', 'text/x-python', 'text/x-rust',
  'application/octet-stream',  // catch-all for source files
]);

// ─── Types ────────────────────────────────────────────────────────────────────

interface FileUploadState {
  file:     File;
  status:   'pending' | 'uploading' | 'done' | 'error';
  progress: number;   // 0–100
  fileId?:  string;
  error?:   string;
}

interface FileDropOverlayProps {
  token:      string;          // Bearer JWT for /ui/upload
  /** Called with the WebSocket input string to inject ("/attach ...") */
  onAttach:   (wsInput: string) => void;
}

// ─── Upload helper ────────────────────────────────────────────────────────────

async function uploadFile(
  file: File,
  token: string,
  onProgress: (pct: number) => void,
): Promise<{ file_id: string; filename: string }> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append('file', file);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE}/ui/upload`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText) as { file_id: string; filename: string };
          resolve(data);
        } catch {
          reject(new Error('Invalid server response'));
        }
      } else {
        try {
          const err = JSON.parse(xhr.responseText) as { detail?: string };
          reject(new Error(err.detail ?? `Upload failed (${xhr.status})`));
        } catch {
          reject(new Error(`Upload failed (${xhr.status})`));
        }
      }
    };

    xhr.onerror = () => reject(new Error('Network error during upload'));
    xhr.send(form);
  });
}

function formatBytes(bytes: number): string {
  if (bytes < 1024)       return `${bytes} B`;
  if (bytes < 1024**2)    return `${(bytes/1024).toFixed(1)} KB`;
  return `${(bytes/1024**2).toFixed(1)} MB`;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function FileDropOverlay({ token, onAttach }: FileDropOverlayProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [uploads,    setUploads]    = useState<FileUploadState[]>([]);
  const dragCounter = useRef(0);

  // ── Global drag event listeners ───────────────────────────────────────────
  useEffect(() => {
    const onDragEnter = (e: DragEvent) => {
      e.preventDefault();
      dragCounter.current++;
      if (dragCounter.current === 1) setIsDragging(true);
    };
    const onDragLeave = () => {
      dragCounter.current--;
      if (dragCounter.current === 0) setIsDragging(false);
    };
    const onDragOver = (e: DragEvent) => { e.preventDefault(); };
    const onDrop     = (e: DragEvent) => {
      e.preventDefault();
      dragCounter.current = 0;
      setIsDragging(false);
      if (e.dataTransfer?.files) handleFiles(Array.from(e.dataTransfer.files));
    };

    window.addEventListener('dragenter', onDragEnter);
    window.addEventListener('dragleave', onDragLeave);
    window.addEventListener('dragover',  onDragOver);
    window.addEventListener('drop',      onDrop);
    return () => {
      window.removeEventListener('dragenter', onDragEnter);
      window.removeEventListener('dragleave', onDragLeave);
      window.removeEventListener('dragover',  onDragOver);
      window.removeEventListener('drop',      onDrop);
    };
  });

  const handleFiles = useCallback((files: File[]) => {
    const valid = files.filter((f) => {
      if (f.size > MAX_BYTES) return false;
      // Accept if MIME matches or is empty (browser didn't detect it)
      return !f.type || ALLOWED_MIME.has(f.type);
    });

    if (valid.length === 0) return;

    const newUploads: FileUploadState[] = valid.map((f) => ({
      file: f, status: 'pending', progress: 0,
    }));
    setUploads((prev) => [...prev, ...newUploads]);

    // Upload each file sequentially
    valid.forEach((file, i) => {
      const idx = uploads.length + i;
      setUploads((prev) => {
        const copy = [...prev];
        copy[idx] = { ...copy[idx], status: 'uploading' };
        return copy;
      });

      uploadFile(
        file,
        token,
        (pct) => setUploads((prev) => {
          const copy = [...prev];
          if (copy[idx]) copy[idx] = { ...copy[idx], progress: pct };
          return copy;
        }),
      )
        .then(({ file_id, filename }) => {
          setUploads((prev) => {
            const copy = [...prev];
            if (copy[idx]) copy[idx] = { ...copy[idx], status: 'done', fileId: file_id, progress: 100 };
            return copy;
          });
          // Inject into agent context via WebSocket
          onAttach(`/attach ${file_id} ${filename}\n`);
          // Auto-clear after 3s
          setTimeout(() => {
            setUploads((prev) => prev.filter((_, j) => j !== idx));
          }, 3_000);
        })
        .catch((err: Error) => {
          setUploads((prev) => {
            const copy = [...prev];
            if (copy[idx]) copy[idx] = { ...copy[idx], status: 'error', error: err.message };
            return copy;
          });
        });
    });
  }, [uploads.length, token, onAttach]);

  if (!isDragging && uploads.length === 0) return null;

  return (
    <>
      {/* Full-screen drop target */}
      {isDragging && (
        <div style={{
          position:   'fixed', inset: 0,
          background: 'rgba(0,255,136,0.06)',
          border:     '3px dashed #00ff88',
          zIndex:     50,
          display:    'flex', alignItems: 'center', justifyContent: 'center',
          pointerEvents: 'none',
          fontFamily: 'monospace',
        }}>
          <div style={{ color: '#00ff88', fontSize: '1.5rem', textAlign: 'center' }}>
            <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>▼</div>
            Drop to attach file to agent context
            <div style={{ color: '#555', fontSize: '0.8rem', marginTop: '0.5rem' }}>
              Max 20 MB · Images, text, code, PDFs
            </div>
          </div>
        </div>
      )}

      {/* Upload progress cards */}
      {uploads.length > 0 && (
        <div style={{
          position:   'fixed', bottom: '1rem', right: '1rem',
          zIndex:     60, display: 'flex', flexDirection: 'column', gap: '0.5rem',
        }}>
          {uploads.map((u, i) => (
            <div key={i} style={{
              background: '#0a0a0a', border: `1px solid ${
                u.status === 'done'  ? '#00ff88' :
                u.status === 'error' ? '#ff4444' : '#555'
              }`,
              padding: '0.6rem 1rem', fontFamily: 'monospace',
              fontSize: '0.75rem', color: '#e0e0e0', minWidth: 260,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 180 }}>
                  {u.file.name}
                </span>
                <span style={{ color: '#555', marginLeft: '0.5rem' }}>{formatBytes(u.file.size)}</span>
              </div>
              {u.status === 'uploading' && (
                <div style={{ marginTop: '0.3rem', background: '#1a1a1a', height: 3 }}>
                  <div style={{ width: `${u.progress}%`, height: '100%', background: '#00ff88', transition: 'width 0.2s' }} />
                </div>
              )}
              {u.status === 'done'  && <div style={{ color: '#00ff88', marginTop: '0.2rem' }}>✓ Attached to context</div>}
              {u.status === 'error' && <div style={{ color: '#ff4444', marginTop: '0.2rem' }}>✗ {u.error}</div>}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
