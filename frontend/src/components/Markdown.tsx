import React from "react"

/** Small, safe markdown renderer for post-mortems: headings, lists, code blocks, tables, bold, inline code. */
function inline(text: string, key: string): React.ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g)
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) return <strong key={`${key}-${i}`} className="text-foreground">{p.slice(2, -2)}</strong>
    if (p.startsWith("`") && p.endsWith("`"))
      return <code key={`${key}-${i}`} className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em] text-foreground">{p.slice(1, -1)}</code>
    if (p.startsWith("*") && p.endsWith("*") && p.length > 2) return <em key={`${key}-${i}`}>{p.slice(1, -1)}</em>
    return p
  })
}

export const Markdown: React.FC<{ source: string }> = ({ source }) => {
  const lines = source.replace(/\r\n/g, "\n").split("\n")
  const out: React.ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (line.startsWith("```")) {
      const lang = line.slice(3)
      const body: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith("```")) body.push(lines[i++])
      i++
      out.push(
        <pre key={i} className="scrollbar-thin my-3 overflow-x-auto rounded-md border bg-muted/30 p-3 font-mono text-xs leading-relaxed">
          {body.map((l, j) => (
            <div key={j} className={lang === "diff" ? (l.startsWith("+") ? "text-success" : l.startsWith("-") ? "text-danger" : "text-muted-foreground") : "text-foreground/80"}>
              {l || " "}
            </div>
          ))}
        </pre>,
      )
      continue
    }
    if (line.startsWith("|")) {
      const rows: string[][] = []
      while (i < lines.length && lines[i].startsWith("|")) {
        const cells = lines[i].split("|").slice(1, -1).map((c) => c.trim())
        if (!cells.every((c) => /^-+$/.test(c))) rows.push(cells)
        i++
      }
      out.push(
        <div key={i} className="scrollbar-thin my-3 overflow-x-auto rounded-md border"><table className="w-full text-xs">
          <tbody>
            {rows.map((r, ri) => (
              <tr key={ri} className={ri === 0 ? "bg-muted/50 font-medium" : "border-t"}>
                {r.map((c, ci) => <td key={ci} className="px-3 py-2 align-top">{inline(c, `${ri}-${ci}`)}</td>)}
              </tr>
            ))}
          </tbody>
        </table></div>,
      )
      continue
    }
    if (line.startsWith("### ")) out.push(<h4 key={i} className="mb-1.5 mt-5 text-sm font-semibold">{line.slice(4)}</h4>)
    else if (line.startsWith("## ")) out.push(<h3 key={i} className="mb-2 mt-1 text-lg font-semibold tracking-tight">{line.slice(3)}</h3>)
    else if (line.startsWith("> ")) out.push(<blockquote key={i} className="my-3 border-l-2 pl-3 text-sm text-muted-foreground">{inline(line.slice(2), `${i}`)}</blockquote>)
    else if (/^\s*- /.test(line)) out.push(<li key={i} className={`${line.startsWith("  ") ? "ml-8" : "ml-4"} list-disc text-sm leading-relaxed text-foreground/85`}>{inline(line.replace(/^\s*- /, ""), `${i}`)}</li>)
    else if (line.trim()) out.push(<p key={i} className="my-1.5 text-sm leading-relaxed text-foreground/85">{inline(line, `${i}`)}</p>)
    i++
  }
  return <div>{out}</div>
}
