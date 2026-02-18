export type SseEvent = {
  event: string
  data: string
}

function parseSseBlock(block: string): SseEvent | null {
  const lines = block.split('\n')
  let event = 'message'
  let dataLines: string[] = []
  for (const raw of lines) {
    const line = raw.replace(/\r$/, '')
    if (line.startsWith('event:')) event = line.slice('event:'.length).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice('data:'.length).trimStart())
  }
  if (!event && dataLines.length === 0) return null
  return { event, data: dataLines.join('\n') }
}

export async function* fetchSse(
  url: string,
  opts: RequestInit
): AsyncGenerator<SseEvent, void, unknown> {
  const res = await fetch(url, opts)
  if (!res.ok) throw new Error(`SSE failed: ${res.status} ${res.statusText}`)
  if (!res.body) throw new Error('SSE failed: empty body')

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })

    while (true) {
      const idx = buf.indexOf('\n\n')
      if (idx === -1) break
      const block = buf.slice(0, idx).trim()
      buf = buf.slice(idx + 2)
      if (!block) continue
      const evt = parseSseBlock(block)
      if (evt) yield evt
    }
  }
}

