/**
 * SSE stream parser for agent execution events.
 *
 * The backend (agents.py) emits standard Server-Sent-Events: each event is
 * `data: {json}\n\n`. This helper reads the fetch Response body as a
 * ReadableStream and yields parsed StreamEvent objects one at a time.
 *
 * Why raw fetch: axios does not expose streaming response bodies in the
 * browser. agentApi.stream() already returns the raw Response; this module
 * turns it into an async iterable of typed events for components to consume.
 */
import type { StreamEvent } from '../services/agent-api'

/**
 * Consume an SSE Response and yield parsed StreamEvent objects.
 *
 * Lines look like:
 *   data: {"type":"final_answer_delta","content":"He"}\n\n
 *   data: {"done":true,"request_id":"...","session_id":"..."}\n\n
 */
export async function* parseSSEStream(response: Response): AsyncGenerator<StreamEvent> {
  if (!response.body) return
  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // SSE events are separated by a blank line (\n\n). Process every
      // complete chunk currently in the buffer.
      let sepIndex: number
      while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
        const rawChunk = buffer.slice(0, sepIndex)
        buffer = buffer.slice(sepIndex + 2)

        const event = parseSSEChunk(rawChunk)
        if (event) yield event
      }
    }
    // Flush any trailing partial event.
    if (buffer.trim()) {
      const event = parseSSEChunk(buffer)
      if (event) yield event
    }
  } finally {
    reader.releaseLock()
  }
}

/**
 * Parse a single SSE chunk (one or more `data:` lines) into a StreamEvent.
 * The backend emits a single JSON object per event on its `data:` line.
 */
function parseSSEChunk(chunk: string): StreamEvent | null {
  const dataLines = chunk
    .split('\n')
    .filter((l) => l.startsWith('data:'))
    .map((l) => l.slice(5).trim())
  if (dataLines.length === 0) return null
  const payload = dataLines.join('\n')
  try {
    return JSON.parse(payload) as StreamEvent
  } catch {
    // Malformed JSON — skip rather than crash the stream.
    return null
  }
}
