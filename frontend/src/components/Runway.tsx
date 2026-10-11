import { t, type Any } from '../api'

/**
 * Coverage runway: hospitals × time. Each cell is "available / required" for credentialed physicians.
 * Column headers mark shift ends so the cause of a drop is visible where it happens.
 */
export function Runway({ coverage, physicians, onlyAttention, onPick, selected }: {
  coverage: Any; physicians?: Any[]; onlyAttention?: boolean; onPick?: (hid: string) => void; selected?: string | null
}) {
  const slots: string[] = coverage.slots
  const ends: Record<string, string[]> = {}
  for (const p of physicians ?? []) {
    if (!p.on_shift || !p.shift_end) continue
    const i = slots.findIndex((s, k) => s >= p.shift_end && (k === 0 || slots[k - 1] < p.shift_end))
    if (i > 0) (ends[slots[i]] ??= []).push(p.name.replace('Dr. ', ''))
  }
  let rows: Any[] = coverage.rows
  if (onlyAttention) rows = rows.filter((r: Any) => r.cells.some((c: Any) => c.status !== 'ok' || c.spike))
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-0 text-sm">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 min-w-[170px] bg-white px-3 pb-2 text-left text-xs font-medium text-ink-soft">Hospital</th>
            {slots.map((s, i) => (
              <th key={s} className="min-w-[58px] px-1 pb-2 align-bottom text-xs font-medium text-ink-soft">
                {ends[s] && <div className="mb-1 rounded bg-navy-100 px-1 py-0.5 text-[10px] font-medium leading-tight text-navy" title={`Shift ends: ${ends[s].join(', ')}`}>{ends[s].length} shift end{ends[s].length > 1 ? 's' : ''}</div>}
                <span className={`num ${i === 0 ? 'font-semibold text-navy' : ''}`}>{i === 0 ? 'Now' : t(s)}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={slots.length + 1} className="p-4 text-center text-ink-soft">Every hospital is above its minimum across the horizon.</td></tr>}
          {rows.map((r: Any) => (
            <tr key={r.hospital_id} onClick={() => onPick?.(r.hospital_id)}
              className={`${onPick ? 'cursor-pointer' : ''} ${selected === r.hospital_id ? 'bg-teal-50' : 'hover:bg-canvas'}`}>
              <td className="sticky left-0 z-10 border-t border-line bg-inherit px-3 py-1.5" style={{ background: selected === r.hospital_id ? '#E8F3F3' : 'white' }}>
                <div className="font-medium leading-tight">{r.hospital_name}</div>
                <div className="text-[11px] text-ink-faint">{r.hospital_id} · tier {r.tier}</div>
              </td>
              {r.cells.map((c: Any) => {
                const cls = c.status === 'gap' ? 'bg-bad text-white' : c.status === 'at_min' ? 'bg-warn-50 text-warn ring-1 ring-inset ring-warn/30' : 'bg-ok-50/60 text-ok'
                const who = c.members.map((m: Any) => `${m.physician_id}${m.kind !== 'on_shift' ? ` (${m.kind.replace('_', ' ')})` : ''}${m.verified ? '' : ' unverified'}`).join(', ')
                return (
                  <td key={c.t} className="border-t border-line px-1 py-1.5 text-center">
                    <div title={`${c.available} available / ${c.required} required${c.spike ? ' (surge +1)' : ''}\n${who || 'nobody'}`}
                      className={`num relative mx-auto rounded-md px-1 py-1 text-xs font-semibold ${cls}`}>
                      {c.available}/{c.required}
                      {c.spike && <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-teal ring-2 ring-white" />}
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex flex-wrap items-center gap-4 px-3 text-xs text-ink-soft">
        <span className="flex items-center gap-1.5"><span className="h-3 w-5 rounded bg-bad" />Below minimum</span>
        <span className="flex items-center gap-1.5"><span className="h-3 w-5 rounded bg-warn-50 ring-1 ring-warn/30" />Exactly at minimum</span>
        <span className="flex items-center gap-1.5"><span className="h-3 w-5 rounded bg-ok-50" />Margin</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-teal" />Demand surge raises requirement +1</span>
        <span>Cells read available / required.</span>
      </div>
    </div>
  )
}
