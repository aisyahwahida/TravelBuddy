import { FormEvent, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowLeftRight,
  Bus,
  ChevronRight,
  Clock,
  Download,
  ExternalLink,
  Footprints,
  LoaderCircle,
  MapPin,
  Plus,
  Sparkles,
  Navigation,
  Timer,
} from "lucide-react";
import type { AlternativePlace, ChatResponse, Place } from "./types";
import GoogleMap from "./GoogleMap";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000/api";

const SRC_COLOR: Record<string, string> = {
  reddit: "#d05a2b",
  openstreetmap: "#5a8a3c",
  google_maps: "#3a72c4",
  curated_must_go: "#bd8f33",
  official_open_data: "#bd8f33",
};

const SRC_LABEL: Record<string, string> = {
  reddit: "Reddit · r/travel",
  openstreetmap: "OpenStreetMap",
  google_maps: "Google Places",
  curated_must_go: "Curated · France list",
  official_open_data: "Official open data",
};

type ChatMessage =
  | { role: "user"; content: string }
  | { role: "assistant"; content: string; response?: ChatResponse };

type RouteSegment = {
  from: Place;
  to: Place;
  distanceKm: number;
  mode: "Walk" | "Metro or bus";
  minutes: number;
};

function haversineKm(from: Place, to: Place) {
  const R = 6371;
  const dLat = ((to.latitude - from.latitude) * Math.PI) / 180;
  const dLon = ((to.longitude - from.longitude) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((from.latitude * Math.PI) / 180) *
      Math.cos((to.latitude * Math.PI) / 180) *
      Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function buildSegments(stops: Place[]): RouteSegment[] {
  return stops.slice(0, -1).map((from, i) => {
    const to = stops[i + 1];
    const d = haversineKm(from, to);
    const walkable = d <= 1.4;
    return {
      from,
      to,
      distanceKm: d,
      mode: walkable ? "Walk" : "Metro or bus",
      minutes: walkable
        ? Math.max(4, Math.round((d / 4.8) * 60))
        : Math.max(12, Math.round((d / 18) * 60 + 8)),
    };
  });
}

function googleMapsUrl(stop: Place) {
  const q = [stop.name, stop.address, stop.neighborhood, stop.city, "France"]
    .filter(Boolean)
    .join(", ");
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}`;
}

function isMuseumCategory(cat: string) {
  return /museum|musée|gallery|galerie/i.test(cat);
}

const MAPS_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY ?? "";

function placePhotoUrl(photoName: string, maxWidth = 400) {
  if (!photoName || !MAPS_KEY) return "";
  return `https://places.googleapis.com/v1/${photoName}/media?maxWidthPx=${maxWidth}&key=${MAPS_KEY}`;
}

function PlacePhoto({
  photoName,
  alt,
  className = "stop-img",
  style,
}: {
  photoName: string;
  alt?: string;
  className?: string;
  style?: React.CSSProperties;
}) {
  const url = placePhotoUrl(photoName);
  if (!url) return <span className={className} style={style} />;
  return (
    <span className={`${className} has-photo`} style={{ ...style }}>
      <img
        src={url}
        alt={alt ?? ""}
        loading="lazy"
        style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
        onError={(e) => {
          const el = e.currentTarget.parentElement as HTMLElement;
          el.className = className ?? "stop-img";
          e.currentTarget.remove();
        }}
      />
    </span>
  );
}

function Stars({ rating }: { rating: number | null }) {
  if (!rating) return null;
  const full = Math.min(5, Math.floor(rating));
  return (
    <span className="stars">
      {Array.from({ length: full }, (_, i) => (
        <svg key={i} viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 2.5l2.9 5.9 6.5.95-4.7 4.58 1.1 6.47L12 17.4l-5.8 3.05 1.1-6.47L2.6 9.35l6.5-.95z" />
        </svg>
      ))}
    </span>
  );
}

function createSessionId() {
  return globalThis.crypto?.randomUUID?.() ?? String(Date.now());
}

const WELCOME: ChatMessage = {
  role: "assistant",
  content:
    "Tell me your France city, dates, interests, and what you want to avoid. I'll build a local-first itinerary from real sourced candidates.",
};

export default function App() {
  const [sessionId, setSessionId] = useState<string>(createSessionId);
  const [message, setMessage] = useState(
    "I will be in Paris for 3 days. I love food markets, bookstores, and calm local neighborhoods. Please avoid tourist traps."
  );
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME]);
  const [result, setResult] = useState<ChatResponse | null>(null);
  const [selectedStopIndex, setSelectedStopIndex] = useState(0);
  const [selectedMapDayIndex, setSelectedMapDayIndex] = useState(0);
  const [activeTab, setActiveTab] = useState<"Map" | "Route" | "Transit">("Map");
  const [loading, setLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState("Planning…");
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const feedRef = useRef<HTMLDivElement | null>(null);

  const mapDaySections =
    result?.itinerary.days?.length
      ? result.itinerary.days
      : result
        ? [{ day: 1, title: "Day 1", summary: "", stops: result.itinerary.stops }]
        : [];

  const activeMapDay =
    mapDaySections[Math.min(selectedMapDayIndex, Math.max(mapDaySections.length - 1, 0))];
  const activeMapStops = activeMapDay?.stops ?? [];
  const selectedStop = activeMapStops[selectedStopIndex] ?? activeMapStops[0] ?? null;
  const segments = buildSegments(activeMapStops);

  const totalWalkMin = segments
    .filter((s) => s.mode === "Walk")
    .reduce((sum, s) => sum + s.minutes, 0);

  const uniqueSources = result
    ? [
        ...new Set(
          result.itinerary.stops
            .map((s) => s.source_type)
            .filter((t) => t && SRC_LABEL[t])
        ),
      ]
    : [];

  const dayStartIndex = mapDaySections
    .slice(0, selectedMapDayIndex)
    .reduce((sum, d) => sum + d.stops.length, 0);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const text = message.trim();
    if (!text) return;

    setLoading(true);
    setLoadingMessage("Analysing your request…");
    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setMessage("");

    try {
      const res = await fetch(`${API_BASE}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          history: messages.map((m) => ({ role: m.role, content: m.content })),
          session_id: sessionId,
        }),
      });
      if (!res.ok) throw new Error("Unable to generate itinerary.");

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            const raw = line.slice(6).trim();
            if (!raw) continue;
            const data = JSON.parse(raw);
            if (currentEvent === "status") {
              setLoadingMessage(data.message);
            } else if (currentEvent === "result") {
              const chat = data as ChatResponse;
              setSessionId(chat.session_id || sessionId);
              setResult(chat);
              setSelectedStopIndex(0);
              setSelectedMapDayIndex(0);
              setMessages((prev) => [
                ...prev,
                { role: "assistant", content: chat.assistant_message, response: chat },
              ]);
            } else if (currentEvent === "error") {
              setError(data.message ?? "Unexpected error.");
            }
            currentEvent = "";
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unexpected error.");
    } finally {
      setLoading(false);
    }
  }

  function handleNewChat() {
    setSessionId(createSessionId());
    setMessage("");
    setMessages([WELCOME]);
    setResult(null);
    setSelectedStopIndex(0);
    setSelectedMapDayIndex(0);
    setError(null);
  }

  async function handleExport() {
    if (!result) return;
    setExporting(true);
    try {
      const res = await fetch(`${API_BASE}/export/pdf`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ itinerary: result.itinerary }),
      });
      if (!res.ok) throw new Error("PDF export failed.");
      const blob = await res.blob();
      window.open(URL.createObjectURL(blob), "_blank", "noopener,noreferrer");
    } catch (err) {
      setError(err instanceof Error ? err.message : "PDF export failed.");
    } finally {
      setExporting(false);
    }
  }

  function handleSwap(alt: AlternativePlace) {
    setMessage(`Swap ${alt.name} into my plan`);
  }

  function handleSelectStop(dayIndex: number, stopIndex: number) {
    setSelectedMapDayIndex(dayIndex);
    setSelectedStopIndex(stopIndex);
  }

  const suggestText =
    result?.alternative_options?.[0]
      ? `Swap ${result.alternative_options[0].name} into the plan`
      : null;

  return (
    <div className="app">
      {/* ── Col 1: Chat ── */}
      <aside className="col chat">
        <header className="chat-top">
          <div className="brand">
            <span className="brand-mark" />
            <div>
              <div className="brand-name">TravelBuddy</div>
              <div className="brand-sub">France</div>
              <div className="tricolore">
                <i /><i /><i />
              </div>
            </div>
          </div>
          <button className="icon-btn" type="button" onClick={handleNewChat} disabled={loading}>
            <Plus size={13} />
            New trip
          </button>
        </header>

        <div className="chat-feed scroll" ref={feedRef}>
          {messages.map((msg, i) => (
            <div className={`msg ${msg.role === "user" ? "user" : "ai"}`} key={i}>
              <div className="msg-role">
                <span className={`avatar ${msg.role === "user" ? "user" : "ai"}`}>
                  {msg.role === "user" ? "Y" : "L"}
                </span>
                <span className="msg-name">{msg.role === "user" ? "You" : "Luxia"}</span>
              </div>
              <div className="bubble">
                {msg.content}
                {"response" in msg && msg.response && (
                  <>
                    <div className="src-row">
                      {[
                        ...new Set(
                          msg.response.itinerary.stops
                            .map((s) => s.source_type)
                            .filter((t) => SRC_LABEL[t])
                        ),
                      ].map((type) => (
                        <span className="src-chip" key={type}>
                          <span className="src-dot" style={{ background: SRC_COLOR[type] }} />
                          {SRC_LABEL[type]}
                        </span>
                      ))}
                    </div>
                    <div className="ai-action">
                      <Sparkles size={13} />
                      {msg.response.itinerary.stops.length} stops ·{" "}
                      {msg.response.extracted_intent.duration_days} days ·{" "}
                      {msg.response.extracted_intent.pace || "mixed"} pace
                    </div>
                  </>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="msg ai">
              <div className="msg-role">
                <span className="avatar ai">L</span>
                <span className="msg-name">Luxia</span>
              </div>
              <div className="bubble" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <LoaderCircle size={14} className="spin" style={{ color: "var(--green)" }} />
                {loadingMessage}
              </div>
            </div>
          )}
        </div>

        <footer className="chat-input">
          {suggestText && !loading && (
            <button
              className="suggest"
              type="button"
              onClick={() => setMessage(suggestText)}
            >
              <Sparkles size={12} />
              {suggestText}
            </button>
          )}
          <div className="input-wrap">
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder='Refine your plan — e.g. "swap stop 4 for something cheaper"…'
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  handleSubmit(e as unknown as FormEvent);
                }
              }}
            />
            <button className="send-btn" type="button" onClick={handleSubmit} disabled={loading}>
              {loading ? <LoaderCircle size={14} className="spin" /> : "Generate plan"}
              <ArrowRight size={14} />
            </button>
          </div>
          {error && <div className="error-note">{error}</div>}
        </footer>
      </aside>

      {/* ── Col 2: Plan ── */}
      <main className="col plan scroll">
        <div className="plan-inner">
          {result ? (
            <>
              <section className="summary">
                <div className="summary-head">
                  <div>
                    <div className="eyebrow" style={{ marginBottom: 10 }}>Votre itinéraire</div>
                    <h1>{result.extracted_intent.destination}</h1>
                    <div className="loc-sub">
                      <span>France</span>
                      <span className="dotsep" />
                      <span>{result.extracted_intent.duration_days} days</span>
                      <span className="dotsep" />
                      <span>Built from your sources</span>
                    </div>
                  </div>
                  <button
                    className="export-btn"
                    type="button"
                    onClick={handleExport}
                    disabled={exporting}
                  >
                    {exporting ? <LoaderCircle size={14} className="spin" /> : <Download size={14} />}
                    Export PDF
                  </button>
                </div>

                <p className="summary-lead">{result.itinerary.summary}</p>

                <div className="meta-strip">
                  <div className="meta">
                    <div className="meta-val">{result.itinerary.stops.length}</div>
                    <div className="meta-lbl">Stops</div>
                  </div>
                  <div className="meta">
                    <div className="meta-val">
                      {totalWalkMin}
                      <span>min</span>
                    </div>
                    <div className="meta-lbl">Walking</div>
                  </div>
                  <div className="meta">
                    <div className="meta-val">
                      {uniqueSources.length}
                      <span>sources</span>
                    </div>
                    <div className="meta-lbl">Verified from</div>
                  </div>
                  <div className="meta">
                    <div className="meta-val">
                      {result.extracted_intent.duration_days}
                      <span>days</span>
                    </div>
                    <div className="meta-lbl">Duration</div>
                  </div>
                </div>
              </section>

              <div className="tagrow">
                {result.itinerary.themes.map((t) => (
                  <span className="tag" key={t}>
                    <span className="tdot" />
                    {t}
                  </span>
                ))}
                {result.extracted_intent.avoid.map((a) => (
                  <span className="tag neg" key={a}>
                    <span className="tdot" />
                    Avoid {a}
                  </span>
                ))}
              </div>

              <div className="days">
                {mapDaySections.map((day, dayIndex) => {
                  const daySegments = buildSegments(day.stops);
                  return (
                    <section key={`${day.day}-${day.title}`}>
                      <div className="day-head">
                        <span className="day-no">Jour {day.day}</span>
                        <span className="day-title">{day.title || `Day ${day.day}`}</span>
                        <span className="day-sub">{day.stops.length} stops</span>
                      </div>
                      <div className="stop-list">
                        {day.stops.map((stop, stopIndex) => {
                          const isActive =
                            dayIndex === selectedMapDayIndex && stopIndex === selectedStopIndex;
                          const seg = daySegments[stopIndex];
                          return (
                            <button
                              key={`${stop.name}-${stopIndex}`}
                              className={`stop${isActive ? " active" : ""}`}
                              type="button"
                              onClick={() => handleSelectStop(dayIndex, stopIndex)}
                            >
                              <span className="stop-num">{stopIndex + 1}</span>
                              <PlacePhoto photoName={stop.photo_name} alt={stop.name} className="stop-img" />
                              <span className="stop-body">
                                <span className="stop-cat">
                                  <span
                                    className={`cat-chip${isMuseumCategory(stop.category) ? " museum" : ""}`}
                                  >
                                    {stop.category || "Place"}
                                  </span>
                                </span>
                                <span className="stop-name">{stop.name}</span>
                                <span className="stop-meta">
                                  {stop.google_rating && (
                                    <span className="mini">
                                      <Stars rating={stop.google_rating} />
                                      <span className="rating-num">{stop.google_rating.toFixed(1)}</span>
                                    </span>
                                  )}
                                  {stop.open_status_label && (
                                    <span className="mini">
                                      <Clock size={12} />
                                      {stop.open_status_label.split(" ").slice(0, 3).join(" ")}
                                    </span>
                                  )}
                                  {stop.source_url ? (
                                    <a
                                      className="src-link"
                                      href={stop.source_url}
                                      target="_blank"
                                      rel="noreferrer"
                                      style={{ color: SRC_COLOR[stop.source_type] ?? "var(--ink-3)" }}
                                      onClick={(e) => e.stopPropagation()}
                                    >
                                      <ExternalLink size={11} />
                                      {SRC_LABEL[stop.source_type] ?? stop.source_type}
                                    </a>
                                  ) : (
                                    <span
                                      className="src-link"
                                      style={{ color: SRC_COLOR[stop.source_type] ?? "var(--ink-3)" }}
                                    >
                                      <ExternalLink size={11} />
                                      {SRC_LABEL[stop.source_type] ?? stop.source_type}
                                    </span>
                                  )}
                                </span>
                              </span>
                              <span className="stop-right">
                                {seg ? (
                                  <span className="walkpill">
                                    {seg.mode === "Walk" ? <Footprints size={11} /> : <Bus size={11} />}
                                    {seg.minutes} min
                                  </span>
                                ) : (
                                  <span />
                                )}
                                <span className="chev">
                                  <ChevronRight size={15} />
                                </span>
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    </section>
                  );
                })}
              </div>

              {result.alternative_options?.length > 0 && (
                <section className="alts">
                  <div className="alts-head">
                    <h3>Alternative places</h3>
                    <span className="hint">Tap swap to drop one into the plan</span>
                  </div>
                  <div className="alts-grid">
                    {result.alternative_options.slice(0, 4).map((alt) => (
                      <div className="alt" key={`${alt.name}-${alt.city}`}>
                        <span className="alt-img" />
                        <span className="alt-body">
                          <span className={`cat-chip${isMuseumCategory(alt.category) ? " museum" : ""}`}>
                            {alt.category || "Place"}
                          </span>
                          <span className="alt-name">{alt.name}</span>
                          {alt.reason && <span className="alt-reason">{alt.reason}</span>}
                        </span>
                        <button
                          className="swap-btn"
                          type="button"
                          onClick={() => handleSwap(alt)}
                        >
                          <ArrowLeftRight size={12} />
                          Swap
                        </button>
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </>
          ) : (
            <div className="plan-empty">
              <MapPin size={32} />
              <h2>Your itinerary appears here</h2>
              <p>Start a conversation to generate a local-first France plan.</p>
            </div>
          )}
        </div>
      </main>

      {/* ── Col 3: Map ── */}
      <aside className="col mapcol">
        <div className="map-tabs">
          {(["Map", "Route", "Transit"] as const).map((tab) => (
            <button
              key={tab}
              className={`map-tab${activeTab === tab ? " active" : ""}`}
              type="button"
              onClick={() => setActiveTab(tab)}
            >
              {tab}
            </button>
          ))}
          <span className="spacer" />
          <span className="map-legend">
            <span className="legend-line" />
            Your route
          </span>
        </div>

        {activeTab === "Map" && (
          <>
            {mapDaySections.length > 1 && (
              <div style={{ display: "flex", gap: 6, padding: "10px 16px 0", flexWrap: "wrap" }}>
                {mapDaySections.map((day, index) => (
                  <button
                    key={`${day.day}-${day.title}`}
                    className={`map-tab${selectedMapDayIndex === index ? " active" : ""}`}
                    type="button"
                    onClick={() => {
                      setSelectedMapDayIndex(index);
                      setSelectedStopIndex(0);
                    }}
                  >
                    Day {day.day}
                  </button>
                ))}
              </div>
            )}

            <div className="map-embed">
              <GoogleMap
                stops={activeMapStops}
                selectedIndex={selectedStopIndex}
                onSelectStop={setSelectedStopIndex}
                startIndex={dayStartIndex}
              />
            </div>

            <div className="detail">
              {selectedStop ? (
                <>
                  <div className={`detail-img${selectedStop.photo_name ? " has-photo" : ""}`}>
                    {selectedStop.photo_name ? (
                      <img
                        src={placePhotoUrl(selectedStop.photo_name, 600)}
                        alt={selectedStop.name}
                        style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
                        onError={(e) => { e.currentTarget.style.display = "none"; }}
                      />
                    ) : null}
                    <span className="detail-stop-no">{selectedStopIndex + 1}</span>
                  </div>
                  <div className="detail-cat">
                    <span className={`cat-chip${isMuseumCategory(selectedStop.category) ? " museum" : ""}`}>
                      {selectedStop.category || "Place"}
                    </span>
                  </div>
                  <div className="detail-top">
                    <div style={{ flex: 1 }}>
                      <div className="detail-name">{selectedStop.name}</div>
                      <div className="detail-sub">
                        {selectedStop.neighborhood || selectedStop.city}
                      </div>
                    </div>
                    {selectedStop.google_rating && (
                      <div className="detail-meta">
                        <Stars rating={selectedStop.google_rating} />
                        <span className="rate-num">{selectedStop.google_rating.toFixed(1)}</span>
                      </div>
                    )}
                  </div>
                  {(selectedStop.local_tip || selectedStop.reason) && (
                    <div className="detail-why">
                      <div className="why-lbl">
                        <span className="eyebrow">Why it's here</span>
                      </div>
                      <div className="why-quote">
                        {selectedStop.local_tip || selectedStop.reason}
                      </div>
                    </div>
                  )}
                  <div className="detail-foot">
                    {segments[selectedStopIndex] ? (
                      <span className="walkpill">
                        {segments[selectedStopIndex].mode === "Walk" ? (
                          <Footprints size={11} />
                        ) : (
                          <Bus size={11} />
                        )}
                        {segments[selectedStopIndex].minutes} min to next
                      </span>
                    ) : (
                      <span style={{ fontSize: 11, color: "var(--ink-4)", fontFamily: "var(--mono)" }}>
                        Last stop
                      </span>
                    )}
                    <a
                      className="openbtn"
                      href={selectedStop.source_url || googleMapsUrl(selectedStop)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <ExternalLink size={12} />
                      Open source
                    </a>
                  </div>
                </>
              ) : (
                <div className="detail-empty">Select a stop to see details</div>
              )}
            </div>

            <div className="legs scroll">
              {segments.length > 0 ? (
                <>
                  <div className="legs-head">
                    <span className="eyebrow">Between stops</span>
                  </div>
                  {segments.map((seg, i) => (
                    <div
                      key={`${seg.from.name}-${seg.to.name}`}
                      className={`leg${i === selectedStopIndex ? " hl" : ""}`}
                    >
                      <span className="leg-route">
                        <span className="leg-no">{i + 1}</span>
                        <span className="leg-arrow">
                          <ArrowRight size={11} />
                        </span>
                        <span className="leg-no">{i + 2}</span>
                      </span>
                      <span className="leg-mode">
                        {seg.mode === "Walk" ? <Footprints size={13} /> : <Bus size={13} />}
                        {seg.mode === "Walk" ? "Walk" : "Metro + walk"}
                      </span>
                      <span className="leg-time">
                        {seg.minutes}
                        <span> min</span>
                      </span>
                    </div>
                  ))}
                </>
              ) : (
                <div style={{ padding: "18px 4px", fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-4)", textAlign: "center" }}>
                  Route appears after plan is generated
                </div>
              )}
            </div>
          </>
        )}

        {activeTab === "Route" && (
          <RoutePanel days={mapDaySections} />
        )}

        {activeTab === "Transit" && (
          <TransitPanel days={mapDaySections} />
        )}
      </aside>
    </div>
  );
}

// ─── Route tab ────────────────────────────────────────────────────────────────

type DaySection = { day: number; title: string; summary: string; stops: Place[] };

function RoutePanel({ days }: { days: DaySection[] }) {
  if (!days.length) {
    return (
      <div className="tab-panel scroll tab-empty">
        <Navigation size={28} />
        <p>Generate a plan to see the full route breakdown.</p>
      </div>
    );
  }

  const allSegs = days.map((day) => ({ day, segs: buildSegments(day.stops) }));
  const totalWalk = allSegs
    .flatMap((d) => d.segs)
    .filter((s) => s.mode === "Walk")
    .reduce((sum, s) => sum + s.minutes, 0);
  const totalTransit = allSegs
    .flatMap((d) => d.segs)
    .filter((s) => s.mode !== "Walk").length;
  const totalKm = allSegs
    .flatMap((d) => d.segs)
    .reduce((sum, s) => sum + s.distanceKm, 0);

  return (
    <div className="tab-panel scroll">
      {/* summary strip */}
      <div className="route-summary">
        <div className="route-stat">
          <span className="route-stat-val">{totalWalk}<span>min</span></span>
          <span className="route-stat-lbl">Walking</span>
        </div>
        <div className="route-stat">
          <span className="route-stat-val">{totalKm.toFixed(1)}<span>km</span></span>
          <span className="route-stat-lbl">Total distance</span>
        </div>
        <div className="route-stat">
          <span className="route-stat-val">{totalTransit}<span>hops</span></span>
          <span className="route-stat-lbl">Metro / bus</span>
        </div>
      </div>

      {allSegs.map(({ day, segs }) => (
        <div className="route-day" key={day.day}>
          <div className="route-day-head">
            <span className="day-no" style={{ fontSize: 9, padding: "4px 8px" }}>
              Jour {day.day}
            </span>
            <span style={{ fontFamily: "var(--serif)", fontSize: 16, fontWeight: 600 }}>
              {day.title || `Day ${day.day}`}
            </span>
            <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-3)", marginLeft: "auto" }}>
              {day.stops.length} stops
            </span>
          </div>

          {segs.length === 0 && (
            <div style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-4)", padding: "8px 0" }}>
              Single stop — no segments
            </div>
          )}

          {segs.map((seg, i) => (
            <div className="route-seg" key={`${seg.from.name}-${i}`}>
              <div className="route-seg-names">
                <span className="route-seg-from">{seg.from.name}</span>
                <ArrowRight size={10} style={{ color: "var(--ink-4)", flexShrink: 0 }} />
                <span className="route-seg-to">{seg.to.name}</span>
              </div>
              <div className="route-seg-meta">
                <span className="walkpill" style={{ fontSize: 10 }}>
                  {seg.mode === "Walk" ? <Footprints size={10} /> : <Bus size={10} />}
                  {seg.mode === "Walk" ? "Walk" : "Metro + walk"}
                </span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-3)" }}>
                  {seg.distanceKm.toFixed(2)} km
                </span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, fontWeight: 600, color: "var(--ink)" }}>
                  {seg.minutes} min
                </span>
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

// ─── Transit tab ──────────────────────────────────────────────────────────────

function toHHMM(minutesFromMidnight: number) {
  const h = Math.floor(minutesFromMidnight / 60) % 24;
  const m = minutesFromMidnight % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function TransitPanel({ days }: { days: DaySection[] }) {
  if (!days.length) {
    return (
      <div className="tab-panel scroll tab-empty">
        <Timer size={28} />
        <p>Generate a plan to see the estimated day schedule.</p>
      </div>
    );
  }

  return (
    <div className="tab-panel scroll">
      {days.map((day) => {
        const segs = buildSegments(day.stops);
        let clock = 9 * 60; // 09:00

        return (
          <div className="transit-day" key={day.day}>
            <div className="route-day-head">
              <span className="day-no" style={{ fontSize: 9, padding: "4px 8px" }}>
                Jour {day.day}
              </span>
              <span style={{ fontFamily: "var(--serif)", fontSize: 16, fontWeight: 600 }}>
                {day.title || `Day ${day.day}`}
              </span>
            </div>

            <div className="timeline">
              {day.stops.map((stop, i) => {
                const arrivalTime = clock;
                const stayMin = stop.estimated_duration_minutes || 60;
                const departTime = arrivalTime + stayMin;
                const seg = segs[i];
                clock = departTime + (seg?.minutes ?? 0);

                return (
                  <div key={`${stop.name}-${i}`}>
                    {/* stop waypoint */}
                    <div className="tl-stop">
                      <div className="tl-time">{toHHMM(arrivalTime)}</div>
                      <div className="tl-dot-col">
                        <div className="tl-dot" />
                        {(seg || i < day.stops.length - 1) && <div className="tl-line" />}
                      </div>
                      <div className="tl-body">
                        <div className="tl-name">{stop.name}</div>
                        <div className="tl-meta">
                          <span className={`cat-chip${isMuseumCategory(stop.category) ? " museum" : ""}`}
                            style={{ fontSize: 10, height: 18, padding: "0 6px" }}>
                            {stop.category || "Place"}
                          </span>
                          <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-3)" }}>
                            {stayMin} min stay · depart {toHHMM(departTime)}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* travel leg to next */}
                    {seg && (
                      <div className="tl-leg">
                        <div className="tl-time tl-time-sm">{toHHMM(departTime)}</div>
                        <div className="tl-dot-col">
                          <div className="tl-leg-icon">
                            {seg.mode === "Walk" ? <Footprints size={10} /> : <Bus size={10} />}
                          </div>
                          <div className="tl-line" />
                        </div>
                        <div className="tl-leg-desc">
                          {seg.mode === "Walk" ? "Walk" : "Metro or bus"} · {seg.distanceKm.toFixed(2)} km · {seg.minutes} min
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}

              {/* end marker */}
              {day.stops.length > 0 && (
                <div className="tl-stop tl-end">
                  <div className="tl-time">{toHHMM(clock)}</div>
                  <div className="tl-dot-col">
                    <div className="tl-dot tl-dot-end" />
                  </div>
                  <div className="tl-body" style={{ color: "var(--ink-3)", fontSize: 12 }}>
                    End of day {day.day}
                  </div>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
