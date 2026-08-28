import { useState } from "react";

import "./_group.css";

type Direction = "helix" | "field" | "atlas";
type Viewport = "desktop" | "mobile" | "compare";

function initialOption<T extends string>(key: string, options: readonly T[], fallback: T): T {
  const value = new URLSearchParams(window.location.search).get(key);
  return options.includes(value as T) ? value as T : fallback;
}

const directionMeta: Record<Direction, { name: string; number: string; tone: string; rationale: string; decisions: string[]; access: string[] }> = {
  helix: {
    name: "Helix",
    number: "01",
    tone: "Quiet authority / layered depth",
    rationale: "A calm, blue-green working surface that makes the private-to-public journey explicit without making the interface feel clinical.",
    decisions: ["Use a persistent space rail", "Keep provenance beside the record", "Reserve teal for scientific status and action"],
    access: ["High-contrast ink on warm surfaces", "Chart labels and point markers accompany the trace", "Status uses text plus shape, never color alone"],
  },
  field: {
    name: "Field Notes",
    number: "02",
    tone: "Editorial / human context",
    rationale: "A paper-and-oxide direction that gives researchers a memorable point of view while preserving rigorous record structure.",
    decisions: ["Pair serif editorial moments with compact data type", "Use paper surfaces for reading rhythm", "Let profile context lead the home view"],
    access: ["Serif display is paired with a readable sans body", "Warm status colors are repeated as labels", "Controls retain strong focus and target sizing"],
  },
  atlas: {
    name: "Signal Atlas",
    number: "03",
    tone: "Instrument panel / discovery",
    rationale: "A denser blueprint language for a growing commons: metadata, trust, and search context are made fast to scan.",
    decisions: ["Treat provenance as first-class navigation", "Use monospaced metadata for comparison", "Keep social activity in a separate visual band"],
    access: ["Dense rows preserve text labels and grouping", "Cool ink meets accessible pale-blue surfaces", "The figure has axes, grid, labels, and a text alternative"],
  },
};

function SpectrumFigure({ compact = false }: { compact?: boolean }) {
  return (
    <svg className={`spectrum-figure ${compact ? "spectrum-figure--compact" : ""}`} viewBox="0 0 520 155" role="img" aria-labelledby="spectrum-title spectrum-description">
      <title id="spectrum-title">Representative Raman spectrum</title>
      <desc id="spectrum-description">Relative intensity plotted against Raman shift. The trace has labeled maxima at approximately 465 and 800 inverse centimetres.</desc>
      <g className="figure-grid"><path d="M38 22H500M38 55H500M38 88H500M38 121H500" /></g>
      <path className="figure-axis" d="M38 12V128H500" />
      <path className="figure-trace" d="M38 100 C72 99 110 95 147 99 C157 98 164 62 170 42 C176 63 182 94 196 98 C232 102 263 92 281 98 C312 101 332 97 340 82 C345 68 348 56 350 52 C355 66 362 93 376 98 C410 101 456 96 500 98" />
      <circle className="figure-peak" cx="170" cy="42" r="3.5" /><circle className="figure-peak" cx="350" cy="52" r="3.5" />
      <text x="18" y="27">1.0</text><text x="18" y="93">0.5</text><text className="figure-axis-title" transform="rotate(-90 11 105)" x="11" y="105">Relative intensity</text>
      <text x="38" y="146">200</text><text x="157" y="146">465</text><text x="338" y="146">800</text><text x="447" y="146">1200 cm⁻¹</text>
    </svg>
  );
}

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "good" | "warn" | "neutral" }) {
  return <span className={`badge badge--${tone}`}><i aria-hidden="true" />{children}</span>;
}

function Frame({ title, eyebrow, children, action }: { title: string; eyebrow: string; children: React.ReactNode; action?: string }) {
  return (
    <article className="screen-frame">
      <header className="screen-header"><div><span className="screen-eyebrow">{eyebrow}</span><h3>{title}</h3></div>{action && <button className="screen-action">{action}</button>}</header>
      <div className="screen-content">{children}</div>
    </article>
  );
}

function MyLab() {
  return <Frame title="My Lab" eyebrow="01 / private home" action="Edit profile">
    <div className="mini-nav"><b>Home</b><span>Library</span><span>Upload</span><span>Processing</span><span>Explore</span></div>
    <div className="profile-row"><div className="avatar">MC</div><div><span className="screen-eyebrow">Researcher profile</span><h4>Dr. Maya Chen</h4><p>Materials Characterization Lab · Raman spectroscopy</p></div></div>
    <div className="home-grid"><div className="inner-card inner-card--attention"><div className="card-top"><div><span className="screen-eyebrow">Needs your attention</span><h4>Hydrated silica — batch 04</h4></div><Badge tone="warn">Needs metadata review</Badge></div><SpectrumFigure compact /><div className="stat-line"><b>532</b> nm · <b>1,024</b> points · <b>38.4</b> SNR</div><button className="link-button">Continue review <span>→</span></button></div><div className="inner-card inner-card--note"><span className="screen-eyebrow">Private workspace</span><h4>Good afternoon, Maya.</h4><p>Raw files, revisions, and processing ledgers stay together here before you publish.</p><button className="link-button">Open Library <span>→</span></button></div></div>
  </Frame>;
}

function Library() {
  const rows = [["Hydrated silica — batch 04", "Private draft", "532 nm · 1,024 pts", "Needs review"], ["Sol-gel series — batch 02", "Private draft", "785 nm · 2,048 pts", "Processing"], ["Quartz reference spectrum", "Public record", "532 nm · 1,024 pts", "Ready"]];
  return <Frame title="Library" eyebrow="02 / My Lab workspace" action="Upload spectrum"><p className="screen-lede">Your spectra, processing history, and publication readiness.</p><span className="privacy-pill">Private by default</span><div className="library-list"><div className="library-row library-row--head"><span>Title</span><span>Visibility</span><span>Acquisition</span><span>Readiness</span></div>{rows.map(([title, visibility, acquisition, readiness], index) => <div className={`library-row ${index === 0 ? "library-row--selected" : ""}`} key={title}><span><b>{title}</b><small>Raman · {index === 0 ? "updated 18 min ago" : "updated yesterday"}</small></span><span className="visibility"><i aria-hidden="true">{index === 2 ? "○" : "▣"}</i>{visibility}</span><span>{acquisition}</span><Badge tone={index === 0 ? "warn" : index === 2 ? "good" : "neutral"}>{readiness}</Badge></div>)}</div><p className="privacy-note"><b>▣</b> Nothing in Library is public until you explicitly publish it.</p></Frame>;
}

function Commons() {
  return <Frame title="Commons" eyebrow="03 / public scientific database" action="Search records"><div className="commons-banner"><div><span className="screen-eyebrow">Raman reference library</span><h4>Find what is <em>citable.</em></h4><p>Search by material, acquisition, provenance, and publication — not engagement.</p></div><label className="search-field"><span className="sr-only">Search Commons records</span><span aria-hidden="true">⌕</span><input type="search" placeholder="Search spectra, materials, DOIs…" /><kbd aria-hidden="true">⌘ K</kbd></label></div><div className="record-grid"><div className="inner-card"><div className="card-top"><Badge tone="good">Verified publication</Badge><span className="license">CC BY 4.0</span></div><h4>Quartz reference spectrum</h4><p className="record-byline">Dr. Maya Chen · Materials Characterization Lab</p><SpectrumFigure /><div className="stat-line"><b>532</b> nm excitation · <b>1,024</b> points · <b>38.4</b> SNR</div></div><aside className="inner-card provenance"><span className="screen-eyebrow">Provenance</span><b>Raw source + 3-step ledger</b><hr /><span className="screen-eyebrow">Publication</span><a href="#doi">10.5281/zenodo.10482031 ↗</a><hr /><span className="screen-eyebrow">Trust boundary</span><p>Scientific rank comes from metadata, quality, provenance, and similarity compatibility. Social activity is not used.</p></aside></div></Frame>;
}

function Feed() {
  return <Frame title="Feed" eyebrow="04 / publication-linked conversation" action="Share an update"><div className="feed-banner"><div><span className="screen-eyebrow">Community layer</span><h4>Talk around the work.</h4><p>Conversation can announce a record and ask a question. It cannot prove one.</p></div><Badge tone="warn">Social ≠ evidence</Badge></div><article className="post-card"><div className="post-author"><div className="avatar avatar--small">MC</div><div><b>Dr. Maya Chen</b><small>Materials Characterization Lab · 2h ago</small></div></div><h4>A cleaner baseline for hydrated silica</h4><p>After three transparent processing steps, the shoulder around 465 cm⁻¹ is easier to inspect. Sharing the record for discussion, not as a substitute for the methods.</p><SpectrumFigure /><div className="linked-row"><div><span className="screen-eyebrow">Linked publication / DOI</span><a href="#doi">10.5281/zenodo.10482031 ↗</a></div><div><span className="screen-eyebrow">Linked dataset</span><a href="#dataset">Quartz reference spectrum ↗</a></div></div><div className="activity-row"><span><b>18</b> reactions</span><span><b>6</b> comments</span><span><b>240</b> views <small>outreach only</small></span><span className="future-slot">Future metric slot · saves</span><span className="future-slot">Future metric slot · downstream reuse</span></div><div className="post-actions"><button>React</button><button>Comment</button><button>Share</button></div></article></Frame>;
}

const views = [{ key: "my-lab", label: "My Lab home", Component: MyLab }, { key: "library", label: "Private Library", Component: Library }, { key: "commons", label: "Public Commons", Component: Commons }, { key: "feed", label: "Feed", Component: Feed }];

export function DesignReview() {
  const [direction, setDirection] = useState<Direction>(() => initialOption("direction", ["helix", "field", "atlas"], "helix"));
  const [viewport, setViewport] = useState<Viewport>(() => initialOption("viewport", ["desktop", "mobile", "compare"], "desktop"));
  const meta = directionMeta[direction];
  return <div className={`design-review design-review--${direction} design-review--${viewport}`}>
    <header className="review-topbar"><div className="wordmark"><span>SI</span><div><b>Spectra Insight</b><small>Design review sandbox</small></div></div><span className="review-status"><i /> Exploration only · no API dependency</span></header>
    <section className="review-hero"><div><span className="review-kicker">Three directions / one product truth</span><h1>Make the boundary<br /><em>impossible to miss.</em></h1><p>A visual study for a Raman-first scientific workspace where private research, the public commons, and community conversation stay connected — without being confused.</p></div><div className="review-controls"><fieldset><legend>Direction</legend><div className="direction-buttons">{(Object.keys(directionMeta) as Direction[]).map(key => <button key={key} onClick={() => setDirection(key)} aria-pressed={direction === key}>{directionMeta[key].number} / {directionMeta[key].name}</button>)}</div></fieldset><fieldset><legend>Viewport treatment</legend><div className="viewport-buttons">{(["desktop", "mobile", "compare"] as Viewport[]).map(key => <button key={key} onClick={() => setViewport(key)} aria-pressed={viewport === key}>{key[0].toUpperCase() + key.slice(1)}</button>)}</div></fieldset></div></section>
    <section className="space-map"><div><span className="section-number">00</span><span><span className="review-kicker">Persistent space map</span><h2>One commons, three permissions.</h2></span></div><div className="map-items"><span className="map-item map-item--private"><b>01</b><strong>My Lab</strong><small>Private by default</small></span><i /><span className="map-item map-item--public"><b>02</b><strong>Commons</strong><small>Published + citable</small></span><i /><span className="map-item map-item--social"><b>03</b><strong>Feed</strong><small>Conversation layer</small></span></div><p>Private work stays yours. Publication status is a scientific decision — never a popularity signal.</p></section>
    <section className="direction-section"><div className="direction-heading"><div><span className="review-kicker">Direction {meta.number}</span><h2>{meta.name}</h2><p>{meta.rationale}</p></div><div className="direction-tone">{meta.tone}</div></div><div className="view-heading"><span>{viewport === "compare" ? "Desktop + mobile treatments" : `${viewport[0].toUpperCase() + viewport.slice(1)} treatment`}</span><i /> <span>Four views / representative content</span></div><div className="screen-grid">{views.map(({ key, Component }) => <div className="view-column" key={key}><span className="view-label">{key === "my-lab" ? "Profile-centered home" : key === "library" ? "Reusable private treatment" : key === "commons" ? "Provenance-rich database" : "Consistent post anatomy"}</span><Component /></div>)}</div></section>
    <section className="direction-notes"><div><span className="review-kicker">Reusable decisions</span><h2>What carries forward.</h2></div><div className="notes-grid"><div><h3>Implementation</h3><ul>{meta.decisions.map(item => <li key={item}>{item}</li>)}</ul></div><div><h3>Accessibility</h3><ul>{meta.access.map(item => <li key={item}>{item}</li>)}</ul></div></div></section>
    <section className="recommendation"><div><span className="section-number">05</span><div><span className="review-kicker">Comparison / recommendation</span><h2>Choose the signal,<br />not the noise.</h2></div></div><div className="recommendation-grid">{(["helix", "field", "atlas"] as Direction[]).map(key => <article className={`recommendation-card recommendation-card--${key}`} key={key}><span>{directionMeta[key].number}</span><h3>{directionMeta[key].name}</h3><p>{key === "helix" ? "Best default for the core product. The clearest hierarchy between private work and published evidence." : key === "field" ? "Best for onboarding and researcher identity. Editorial typography gives the publication story human presence." : "Best for discovery and large-scale browsing. Provenance and navigation become highly scannable."}</p><b>{key === "helix" ? "Product foundation" : key === "field" ? "Profile + storytelling" : "Commons + exploration"}</b></article>)}</div></section>
    <footer className="review-footer"><div><span className="review-kicker">Review notes</span><h2>Readable under pressure.</h2></div><ul><li>Charts use a solid trace, point markers, grid, axis labels, and a text summary — never color alone.</li><li>Private, public, and social states use labels, icons, and structure in addition to color.</li><li>Unavailable analytics are labeled future metric slots, not live claims.</li><li>All controls are keyboard reachable with visible state and mobile-sized targets.</li></ul></footer>
  </div>;
}