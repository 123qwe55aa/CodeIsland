
/**
 * Static macOS-style screen content for the MacbookScroll component.
 * Shows a desktop with notch UI expanded and terminal windows.
 */
export default function MacScreenContent() {
  return (
    <div
      className="relative w-full h-full"
      style={{
        background: 'linear-gradient(135deg, #1a0533 0%, #0c1445 25%, #1e3a5f 50%, #3a1d5c 75%, #1a0533 100%)',
      }}
    >
      {/* Wallpaper orbs */}
      <div className="absolute top-1/4 left-1/3 w-1/3 aspect-square rounded-full bg-purple-600/20 blur-[60px]" />
      <div className="absolute bottom-1/4 right-1/4 w-1/4 aspect-square rounded-full bg-blue-500/15 blur-[40px]" />
      <div className="absolute top-1/2 right-1/3 w-1/4 aspect-square rounded-full bg-pink-500/10 blur-[50px]" />

      {/* Menu bar */}
      <div
        className="relative flex items-center justify-between px-3 h-[6%]"
        style={{ background: 'rgba(0,0,0,0.3)', backdropFilter: 'blur(10px)' }}
      >
        <div className="flex items-center gap-3 font-mono text-[8px] text-white/80">
          <span className="font-bold"></span>
          <span>CodeIsland</span>
          <span className="text-white/50">File</span>
          <span className="text-white/50">Edit</span>
          <span className="text-white/50">Window</span>
        </div>

        {/* Notch — expanded */}
        <div className="absolute left-1/2 -translate-x-1/2 top-0 z-10">
          <div className="bg-black rounded-b-xl px-2 pt-0.5 pb-1.5 min-w-[180px]">
            <div className="flex items-center justify-between mb-1 pb-0.5 border-b border-white/[0.06]">
              <span className="font-mono text-[6px] text-white/40">3 sessions</span>
              <span className="font-mono text-[6px] text-white/30">⚙</span>
            </div>
            {[
              { name: "fix auth bug", color: "#34d399", time: "12m" },
              { name: "optimize queries", color: "#fbbf24", time: "5m" },
              { name: "deploy api", color: "#34d399", time: "2m" },
            ].map((s) => (
              <div key={s.name} className="flex items-center gap-1 py-0.5 text-[7px]">
                <div className="w-1 h-1 rounded-full shrink-0" style={{ background: s.color, boxShadow: `0 0 3px ${s.color}60` }} />
                <span className="text-white/80 truncate">{s.name}</span>
                <span className="ml-auto text-white/30 font-mono text-[6px] shrink-0">{s.time}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2 font-mono text-[7px] text-white/50">
          <span>Wi-Fi</span>
          <span>19:30</span>
        </div>
      </div>

      {/* Terminal windows */}
      <div className="relative px-3 pt-[12%] pb-3 flex gap-2 h-[94%]">
        {/* Terminal 1 */}
        <div className="flex-1 rounded-lg overflow-hidden border border-white/[0.08]" style={{ background: 'rgba(22,22,30,0.95)' }}>
          <div className="flex items-center gap-1 px-2 py-1 border-b border-white/[0.06]">
            <div className="w-1.5 h-1.5 rounded-full bg-[#ff5f57]" />
            <div className="w-1.5 h-1.5 rounded-full bg-[#febc2e]" />
            <div className="w-1.5 h-1.5 rounded-full bg-[#28c840]" />
            <span className="ml-1 font-mono text-[6px] text-white/40">claude — fix-auth-bug</span>
          </div>
          <div className="p-2 font-mono text-[7px] leading-relaxed">
            <div><span className="text-[#34d399]">●</span> <span className="text-white/70">Let me look at the auth module.</span></div>
            <div className="mt-1"><span className="text-[#a78bfa]">●</span> <span className="text-white/50">Searching for 6 patterns...</span></div>
            <div className="mt-1"><span className="text-[#a78bfa]">●</span> <span className="text-white/50">Read 2 files</span></div>
            <div className="mt-1.5 rounded border border-white/[0.06] overflow-hidden">
              <div className="bg-[#34d399]/10 text-[#34d399]/80 px-1.5 py-0.5 text-[6px]">+ if (!token) throw new AuthError('missing');</div>
              <div className="bg-red-500/10 text-red-400/80 px-1.5 py-0.5 text-[6px]">- jwt.verify(token);</div>
            </div>
            <div className="mt-1.5"><span className="text-[#34d399]">●</span> <span className="text-white/70">All checks passing.</span></div>
          </div>
        </div>

        {/* Terminal 2 */}
        <div className="flex-1 rounded-lg overflow-hidden border border-white/[0.08]" style={{ background: 'rgba(22,22,30,0.95)' }}>
          <div className="flex items-center gap-1 px-2 py-1 border-b border-white/[0.06]">
            <div className="w-1.5 h-1.5 rounded-full bg-[#ff5f57]" />
            <div className="w-1.5 h-1.5 rounded-full bg-[#febc2e]" />
            <div className="w-1.5 h-1.5 rounded-full bg-[#28c840]" />
            <span className="ml-1 font-mono text-[6px] text-white/40">claude — optimize-queries</span>
          </div>
          <div className="p-2 font-mono text-[7px] leading-relaxed">
            <div><span className="text-[#fbbf24]">●</span> <span className="text-white/70">Analyzing the slow queries.</span></div>
            <div className="mt-1"><span className="text-[#a78bfa]">●</span> <span className="text-white/50">Read(schema.prisma)</span></div>
            <div className="mt-0.5 text-white/30 text-[6px]">— 2.3 MB</div>
            <div className="mt-1"><span className="text-[#a78bfa]">●</span> <span className="text-white/50">Edit(src/db/queries.ts)</span></div>
          </div>
        </div>
      </div>
    </div>
  )
}
