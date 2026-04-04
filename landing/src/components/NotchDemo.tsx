import { useState, useEffect, useCallback } from "react"
import { motion, AnimatePresence } from "motion/react"
import { LayoutGrid, ShieldCheck, MessageSquare, ArrowRight } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import logo from "../lib/logo"

type DemoState = "monitor" | "approve" | "ask" | "jump"

const pills: { id: DemoState; label: string; Icon: LucideIcon }[] = [
  { id: "monitor", label: "Monitor", Icon: LayoutGrid },
  { id: "approve", label: "Approve", Icon: ShieldCheck },
  { id: "ask", label: "Ask", Icon: MessageSquare },
  { id: "jump", label: "Jump", Icon: ArrowRight },
]

const MonitorView = () => (
  <div className="space-y-3">
    <div className="text-xs text-text-muted font-mono mb-4">2 active sessions</div>
    {[
      { name: "fix auth bug", status: "working", tool: "Bash: npm test", time: "12m", color: "bg-green" },
      { name: "optimize queries", status: "waiting", tool: "Read: schema.prisma", time: "5m", color: "bg-amber" },
    ].map((s) => (
      <div key={s.name} className="flex items-center gap-3 p-3 rounded-lg bg-white/[0.03] border border-white/[0.04]">
        <div className={`w-2 h-2 rounded-full ${s.color} shrink-0`} style={{ boxShadow: s.color === 'bg-green' ? '0 0 8px rgba(52,211,153,0.5)' : '0 0 8px rgba(251,191,36,0.5)' }} />
        <div className="flex-1 min-w-0">
          <div className="text-sm text-text-primary font-medium truncate">{s.name}</div>
          <div className="text-xs text-text-muted font-mono">{s.tool}</div>
        </div>
        <span className="text-xs text-text-muted font-mono shrink-0">{s.time}</span>
      </div>
    ))}
  </div>
)

const ApproveView = () => (
  <div className="space-y-3">
    <div className="text-xs text-amber font-mono flex items-center gap-2">
      <ShieldCheck size={12} /> Permission Request
    </div>
    <div className="text-xs text-text-muted font-mono">Edit: src/auth/middleware.ts</div>
    <div className="rounded-lg overflow-hidden border border-white/[0.06] text-xs font-mono">
      <div className="bg-red-500/10 text-red-400 px-3 py-1.5 border-b border-white/[0.04]">
        - jwt.verify(token);
      </div>
      <div className="bg-green/10 text-green px-3 py-1.5">
        + if (!token) throw new AuthError('missing');
      </div>
    </div>
    <div className="flex gap-2 pt-1">
      <button className="flex-1 py-2 rounded-lg bg-green/15 text-green text-xs font-mono border border-green/20 hover:bg-green/25 transition-colors">Allow</button>
      <button className="flex-1 py-2 rounded-lg bg-red-500/10 text-red-400 text-xs font-mono border border-red-500/15 hover:bg-red-500/15 transition-colors">Deny</button>
    </div>
  </div>
)

const AskView = () => (
  <div className="space-y-3">
    <div className="text-xs text-purple-light font-mono flex items-center gap-2">
      <MessageSquare size={12} /> Claude is asking
    </div>
    <div className="p-3 rounded-lg bg-white/[0.03] border border-white/[0.04]">
      <p className="text-sm text-text-secondary leading-relaxed">
        "Should I also update the refresh token logic to match the new auth pattern?"
      </p>
    </div>
    <div className="flex gap-2">
      <button className="flex-1 py-2 rounded-lg bg-green/15 text-green text-xs font-mono border border-green/20">Yes</button>
      <button className="flex-1 py-2 rounded-lg bg-amber/10 text-amber text-xs font-mono border border-amber/15">No</button>
      <button className="flex-1 py-2 rounded-lg bg-purple-accent/10 text-purple-light text-xs font-mono border border-purple-accent/15">Jump</button>
    </div>
  </div>
)

const JumpView = () => (
  <div className="space-y-3">
    <div className="text-xs text-green font-mono flex items-center gap-2">
      <ArrowRight size={12} /> Jumping to terminal
    </div>
    <div className="p-4 rounded-lg bg-white/[0.03] border border-white/[0.04] text-center">
      <div className="font-mono text-2xl text-green glow-green mb-2">→→→</div>
      <div className="text-sm text-text-primary font-medium">fix-auth-bug</div>
      <div className="text-xs text-text-muted font-mono mt-1">cmux  ·  tab 3  ·  split 1</div>
    </div>
  </div>
)

const views: Record<DemoState, React.FC> = { monitor: MonitorView, approve: ApproveView, ask: AskView, jump: JumpView }
const descriptions: Record<DemoState, { title: string; sub: string }> = {
  monitor: { title: "Monitor all sessions", sub: "See every running agent at a glance — status, tool calls, duration." },
  approve: { title: "Approve without switching", sub: "Review code diffs and allow or deny — right from the notch." },
  ask: { title: "Answer from the notch", sub: "When an agent needs input, pick an option and keep moving." },
  jump: { title: "Jump to the right terminal", sub: "One click to the exact tab and split pane in cmux or iTerm2." },
}

export default function NotchDemo() {
  const [active, setActive] = useState<DemoState>("monitor")
  const [paused, setPaused] = useState(false)

  const cycle = useCallback(() => {
    setActive((p) => {
      const idx = pills.findIndex((x) => x.id === p)
      return pills[(idx + 1) % pills.length].id
    })
  }, [])

  useEffect(() => {
    if (paused) return
    const t = setInterval(cycle, 4000)
    return () => clearInterval(t)
  }, [paused, cycle])

  const pick = (id: DemoState) => {
    setActive(id)
    setPaused(true)
    setTimeout(() => setPaused(false), 12000)
  }

  const View = views[active]
  const desc = descriptions[active]

  return (
    <section id="demo" className="relative z-20 py-32 px-6 noise bg-deep">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_60%_at_50%_50%,rgba(124,58,237,0.05)_0%,transparent_70%)]" />

      <div className="max-w-3xl mx-auto relative z-10">
        <div
          style={{ animation: 'heroEnter 0.8s ease-out both' }}
          className="text-center mb-16"
        >
          <span className="font-mono text-xs text-green uppercase tracking-[0.3em]">interactive demo</span>
          <h2 className="font-display text-4xl sm:text-5xl font-extrabold text-text-primary mt-4">
            See it in action
          </h2>
        </div>

        {/* Notch mockup */}
        <div
          style={{ animation: 'heroEnter 0.8s ease-out 0.1s both' }}
          className="mx-auto max-w-md"
        >
          {/* Notch shape */}
          <div className="relative">
            <div className="bg-black rounded-b-3xl pt-3 pb-5 px-5 border border-white/[0.06] border-t-0 shadow-[0_20px_80px_rgba(0,0,0,0.6),0_0_0_1px_rgba(255,255,255,0.03)_inset]">
              {/* Notch bar */}
              <div className="flex items-center justify-between mb-4 pb-3 border-b border-white/[0.05]">
                <div className="flex items-center gap-2">
                  <img src={logo} alt="" className="w-6 h-6 rounded-sm" />
                  <span className="font-mono text-xs text-text-secondary">myproject</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-1.5 h-1.5 rounded-full bg-green" style={{ boxShadow: '0 0 6px rgba(52,211,153,0.5)' }} />
                  <span className="font-mono text-[10px] text-text-muted">2 active</span>
                </div>
              </div>

              {/* Dynamic content */}
              <AnimatePresence mode="wait">
                <motion.div
                  key={active}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  transition={{ duration: 0.25 }}
                  className="min-h-[180px]"
                >
                  <View />
                </motion.div>
              </AnimatePresence>
            </div>
          </div>
        </div>

        {/* Pills */}
        <div className="flex justify-center gap-2 mt-10">
          {pills.map((p) => (
            <button
              key={p.id}
              onClick={() => pick(p.id)}
              className={`flex items-center gap-1.5 font-mono text-xs px-4 py-2 rounded-full border transition-all duration-300 cursor-pointer ${
                active === p.id
                  ? "bg-green/10 border-green/25 text-green shadow-[0_0_16px_rgba(52,211,153,0.1)]"
                  : "border-white/[0.06] text-text-muted hover:border-white/[0.12] hover:text-text-secondary"
              }`}
            >
              <p.Icon size={12} />
              {p.label}
            </button>
          ))}
        </div>

        {/* Description */}
        <AnimatePresence mode="wait">
          <motion.div
            key={active}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="text-center mt-8"
          >
            <h3 className="font-display text-2xl font-bold text-text-primary">{desc.title}</h3>
            <p className="text-sm text-text-muted mt-2 max-w-md mx-auto">{desc.sub}</p>
          </motion.div>
        </AnimatePresence>
      </div>
    </section>
  )
}
