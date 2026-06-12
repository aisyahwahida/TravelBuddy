import { FormEvent, useEffect, useRef, useState } from "react";
import {
  Compass,
  Download,
  ExternalLink,
  Footprints,
  LoaderCircle,
  Map,
  MapPin,
  MessageCircle,
  Plus,
  Route,
  Send,
} from "lucide-react";

import type { AlternativePlace, ChatResponse, Place } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000/api";

const starterPrompt =
  "I will be in Paris for 3 days. I love food markets, bookstores, and calm local neighborhoods. Please avoid tourist traps.";
const welcomeMessage =
  "Tell me your France city, dates, interests, and what you want to avoid.";

function createSessionId() {
  return globalThis.crypto?.randomUUID?.() ?? String(Date.now());
}

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

type MapPoint = {
  stop: Place;
  index: number;
  x: number;
  y: number;
};

type RouteSegment = {
  from: Place;
  to: Place;
  distanceKm: number;
  mode: "Walk" | "Metro or bus";
  minutes: number;
};

function distanceKm(from: Place, to: Place) {
  const earthRadiusKm = 6371;
  const latDelta = ((to.latitude - from.latitude) * Math.PI) / 180;
  const lonDelta = ((to.longitude - from.longitude) * Math.PI) / 180;
  const fromLat = (from.latitude * Math.PI) / 180;
  const toLat = (to.latitude * Math.PI) / 180;
  const a =
    Math.sin(latDelta / 2) ** 2 +
    Math.cos(fromLat) * Math.cos(toLat) * Math.sin(lonDelta / 2) ** 2;

  return earthRadiusKm * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function buildRouteSegments(stops: Place[]): RouteSegment[] {
  return stops.slice(0, -1).map((from, index) => {
    const to = stops[index + 1];
    const distance = distanceKm(from, to);
    const walkable = distance <= 1.4;

    return {
      from,
      to,
      distanceKm: distance,
      mode: walkable ? "Walk" : "Metro or bus",
      minutes: walkable
        ? Math.max(4, Math.round((distance / 4.8) * 60))
        : Math.max(12, Math.round((distance / 18) * 60 + 8)),
    };
  });
}

function buildMapPoints(stops: Place[]): MapPoint[] {
  if (!stops.length) return [];

  const latitudes = stops.map((stop) => stop.latitude);
  const longitudes = stops.map((stop) => stop.longitude);
  const minLat = Math.min(...latitudes);
  const maxLat = Math.max(...latitudes);
  const minLon = Math.min(...longitudes);
  const maxLon = Math.max(...longitudes);
  const latSpan = maxLat - minLat || 0.01;
  const lonSpan = maxLon - minLon || 0.01;

  return stops.map((stop, index) => ({
    stop,
    index,
    x: 12 + ((stop.longitude - minLon) / lonSpan) * 76,
    y: 88 - ((stop.latitude - minLat) / latSpan) * 76,
  }));
}

function googleMapsLocationUrl(stop: Place) {
  const parts = [
    stop.name,
    stop.address,
    stop.neighborhood,
    stop.city,
    "France",
  ].filter(Boolean);
  const query = encodeURIComponent(parts.join(", "));
  return `https://www.google.com/maps/search/?api=1&query=${query}`;
}

export default function App() {
  const [sessionId, setSessionId] = useState<string>(() => createSessionId());
  const [message, setMessage] = useState(starterPrompt);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content: welcomeMessage,
    },
  ]);
  const [result, setResult] = useState<ChatResponse | null>(null);
  const [selectedStopIndex, setSelectedStopIndex] = useState(0);
  const [selectedMapDayIndex, setSelectedMapDayIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState("Planning...");
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mapDaySections =
    result?.itinerary.days && result.itinerary.days.length
      ? result.itinerary.days
      : result
        ? [{ day: 1, title: "Day 1", summary: "", stops: result.itinerary.stops }]
        : [];
  const activeMapDay =
    mapDaySections[Math.min(selectedMapDayIndex, Math.max(mapDaySections.length - 1, 0))];
  const activeMapStops = activeMapDay?.stops ?? [];
  const selectedStop =
    activeMapStops[selectedStopIndex] ?? activeMapStops[0] ?? null;
  const mapPoints = buildMapPoints(activeMapStops);
  const routeSegments = buildRouteSegments(activeMapStops);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmedMessage = message.trim();
    if (!trimmedMessage) return;

    setLoading(true);
    setLoadingMessage("Analyzing your request...");
    setError(null);
    setMessages((current) => [
      ...current,
      { role: "user", content: trimmedMessage },
    ]);
    setMessage("");

    try {
      const response = await fetch(`${API_BASE}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: trimmedMessage,
          history: messages.map((item) => ({
            role: item.role,
            content: item.content,
          })),
          session_id: sessionId,
        }),
      });

      if (!response.ok) {
        throw new Error("Unable to generate itinerary.");
      }

      const reader = response.body!.getReader();
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
              const chatData = data as ChatResponse;
              setSessionId(chatData.session_id || sessionId);
              setResult(chatData);
              setSelectedStopIndex(0);
              setSelectedMapDayIndex(0);
              setMessages((current) => [
                ...current,
                { role: "assistant", content: chatData.assistant_message },
              ]);
            } else if (currentEvent === "error") {
              setError(data.message ?? "Unexpected error occurred.");
            }
            currentEvent = "";
          }
        }
      }
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Unexpected error occurred.",
      );
    } finally {
      setLoading(false);
    }
  }

  function handleNewChat() {
    setSessionId(createSessionId());
    setMessage("");
    setMessages([{ role: "assistant", content: welcomeMessage }]);
    setResult(null);
    setSelectedStopIndex(0);
    setSelectedMapDayIndex(0);
    setError(null);
    setLoadingMessage("Planning...");
  }

  async function handleExportPdf() {
    if (!result) return;

    setExporting(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/export/pdf`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ itinerary: result.itinerary }),
      });

      if (!response.ok) {
        throw new Error("Unable to export PDF.");
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (exportError) {
      setError(
        exportError instanceof Error
          ? exportError.message
          : "PDF export failed.",
      );
    } finally {
      setExporting(false);
    }
  }

  return (
    <main className="website-stage">
      <section className="app-shell" aria-label="TravelBuddy web app">
        <header className="app-header">
          <div>
            <p>TravelBuddy</p>
            <h1>Where Local Insights Meet Smart Planning</h1>
            <span>
              Get personalized itineraries with hidden cafés, local food spots,
              free museums, and routes backed by real community and map-based
              data powered by AI-based planning.
            </span>
          </div>
          <button
            className="export-button"
            type="button"
            onClick={handleExportPdf}
            disabled={!result || exporting}
            title="Open PDF"
          >
            {exporting ? <LoaderCircle className="spin" /> : <Download />}
            Export PDF
          </button>
        </header>

        <div className="dashboard-grid">
          <section className="panel chat-panel" aria-label="Chat">
            <div className="chat-heading-row">
              <div className="panel-heading">
                <MessageCircle />
                <div>
                  <p>Chat</p>
                  <h2>Tell us your trip style</h2>
                </div>
              </div>
              <button
                className="new-chat-button"
                type="button"
                onClick={handleNewChat}
                disabled={loading}
                title="Start a new chat"
              >
                <Plus />
                New chat
              </button>
            </div>

            <div className="messages">
              {messages.map((item, index) => (
                <div
                  className={`message ${item.role}`}
                  key={`${item.role}-${index}`}
                >
                  {item.content}
                </div>
              ))}
              {loading ? (
                <div className="message assistant loading-line">
                  <LoaderCircle size={16} className="spin" />
                  {loadingMessage}
                </div>
              ) : null}
              <div ref={messagesEndRef} />
            </div>

            <form className="web-composer" onSubmit={handleSubmit}>
              <textarea
                aria-label="Travel request"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                rows={5}
              />
              <button type="submit" disabled={loading} title="Send request">
                {loading ? <LoaderCircle className="spin" /> : <Send />}
                Generate plan
              </button>
            </form>

            {error ? <p className="error-text">{error}</p> : null}
          </section>

          <section className="panel plan-panel" aria-label="Itinerary">
            <div className="panel-heading">
              <Route />
              <div>
                <p>Plan</p>
                <h2>{result?.extracted_intent.destination ?? "France"}</h2>
              </div>
            </div>

              {result ? (
                <>
                  <div className="plan-summary">
                    <p>{result.itinerary.destination}</p>
                    <h2>{result.itinerary.title}</h2>
                    <span>{result.itinerary.summary}</span>
                  </div>

                  <div className="theme-row">
                    {result.itinerary.themes.map((theme) => (
                      <span key={theme}>{theme}</span>
                    ))}
                  </div>

                  <IntentSnapshot result={result} />

                  <DayPlan
                    days={result.itinerary.days}
                    fallbackStops={result.itinerary.stops}
                    selectedStopIndex={selectedStopIndex}
                    selectedDayIndex={selectedMapDayIndex}
                    onSelectStop={(dayIndex, index) => {
                      setSelectedMapDayIndex(dayIndex);
                      setSelectedStopIndex(index);
                    }}
                  />

                  <div className="notes-list">
                    {[
                      ...result.itinerary.avoidance_notes,
                      ...result.itinerary.practical_notes,
                    ].map((note) => (
                      <p key={note}>{note}</p>
                    ))}
                  </div>

                  <EvidenceList evidence={result.evidence} />

                  {result.alternative_options?.length > 0 && (
                    <AlternativesList alternatives={result.alternative_options} />
                  )}
                </>
              ) : (
                <EmptyState
                  icon={<Compass size={28} />}
                  title="Plan appears here"
                  body="Start in chat to generate a local-first France itinerary."
                />
              )}
          </section>

          <section className="panel map-panel" aria-label="Map">
            <div className="panel-heading">
              <Map />
              <div>
                <p>Map</p>
                <h2>Route preview</h2>
              </div>
            </div>

              {selectedStop ? (
                <>
                  {mapDaySections.length > 1 ? (
                    <div className="map-day-tabs" aria-label="Map day tabs">
                      {mapDaySections.map((day, index) => (
                        <button
                          className={index === selectedMapDayIndex ? "active" : ""}
                          type="button"
                          key={`${day.day}-${day.title}`}
                          onClick={() => {
                            setSelectedMapDayIndex(index);
                            setSelectedStopIndex(0);
                          }}
                        >
                          Day {day.day}
                        </button>
                      ))}
                    </div>
                  ) : null}

                  <div className="route-map" aria-label="Suggested places map">
                    <svg className="route-lines" viewBox="0 0 100 100">
                      {mapPoints.slice(0, -1).map((point, index) => {
                        const nextPoint = mapPoints[index + 1];
                        return (
                          <line
                            key={`${point.stop.name}-${nextPoint.stop.name}`}
                            x1={point.x}
                            y1={point.y}
                            x2={nextPoint.x}
                            y2={nextPoint.y}
                          />
                        );
                      })}
                    </svg>

                    {mapPoints.map((point) => (
                      <button
                        className={`map-pin ${
                          point.index === selectedStopIndex ? "active" : ""
                        }`}
                        type="button"
                        key={`${point.stop.name}-${point.index}`}
                        style={{ left: `${point.x}%`, top: `${point.y}%` }}
                        onClick={() => setSelectedStopIndex(point.index)}
                        title={point.stop.name}
                      >
                        {point.index + 1}
                      </button>
                    ))}
                  </div>

                  <div className="map-stop-card">
                    <div>
                      <p>{activeMapDay?.title ?? "Selected stop"}</p>
                      <h2>{selectedStop.name}</h2>
                      <span>{selectedStop.local_tip}</span>
                      <small>
                        {selectedStop.best_time} / {selectedStop.tourist_trap_risk} risk
                      </small>
                      <PlaceStatus stop={selectedStop} compact />
                      <SourceLine stop={selectedStop} compact asLink />
                    </div>
                    <a
                      className="round-button"
                      href={googleMapsLocationUrl(selectedStop)}
                      target="_blank"
                      rel="noreferrer"
                      title="Open exact location in Google Maps"
                    >
                      <ExternalLink />
                    </a>
                  </div>

                  <div className="route-list" aria-label="Distances between stops">
                    {routeSegments.map((segment, index) => (
                      <article
                        className="route-step"
                        key={`${segment.from.name}-${segment.to.name}`}
                      >
                        <span className="route-step-icon">
                          {segment.mode === "Walk" ? <Footprints /> : <Route />}
                        </span>
                        <div>
                          <strong>
                            {index + 1} to {index + 2}: {segment.distanceKm.toFixed(1)} km
                          </strong>
                          <small>
                            {segment.mode} / about {segment.minutes} min
                          </small>
                          <em>
                            {segment.from.name} to {segment.to.name}
                          </em>
                        </div>
                      </article>
                    ))}
                  </div>
                </>
              ) : (
                <EmptyState
                  icon={<MapPin size={28} />}
                  title="Map appears here"
                  body="Generate a plan and choose a stop to preview it."
                />
              )}
          </section>
        </div>
      </section>
    </main>
  );
}

function IntentSnapshot({ result }: { result: ChatResponse }) {
  const intent = result.extracted_intent;
  const chips = [
    intent.duration_days ? `${intent.duration_days} day plan` : "",
    intent.pace ? `${intent.pace} pace` : "",
    intent.budget ? `budget: ${intent.budget}` : "",
    intent.mood ? `mood: ${intent.mood}` : "",
    intent.travel_style ? `style: ${intent.travel_style}` : "",
  ].filter(Boolean);

  if (!chips.length) return null;

  return (
    <div className="intent-snapshot" aria-label="Extracted preferences">
      {chips.map((chip) => (
        <span key={chip}>{chip}</span>
      ))}
    </div>
  );
}

function EvidenceList({ evidence }: { evidence: ChatResponse["evidence"] }) {
  if (!evidence.length) {
    return (
      <div className="evidence-list">
        <p>
          Evidence: refresh Reddit and OpenStreetMap data to attach source links
          to each recommendation.
        </p>
      </div>
    );
  }

  return (
    <div className="evidence-list" aria-label="Recommendation evidence">
      <strong>Why these are trusted</strong>
      {evidence.slice(0, 5).map((item) => (
        <a
          href={item.source_url}
          key={`${item.place_name}-${item.source_url}`}
          target="_blank"
          rel="noreferrer"
        >
          <span>{item.place_name}</span>
          <small>
            {sourceLabel(item.source_type)} /{" "}
            {item.source_title}
          </small>
        </a>
      ))}
    </div>
  );
}

function EmptyState({
  icon,
  title,
  body,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="empty-state">
      {icon}
      <h2>{title}</h2>
      <p>{body}</p>
    </div>
  );
}

function DayPlan({
  days,
  fallbackStops,
  selectedStopIndex,
  selectedDayIndex,
  onSelectStop,
}: {
  days: ChatResponse["itinerary"]["days"];
  fallbackStops: Place[];
  selectedStopIndex: number;
  selectedDayIndex: number;
  onSelectStop: (dayIndex: number, index: number) => void;
}) {
  const daySections =
    days && days.length
      ? days
      : [{ day: 1, title: "Day 1", summary: "", stops: fallbackStops }];

  return (
    <div className="day-list">
      {daySections.map((day, dayIndex) => (
        <section className="day-section" key={`${day.day}-${day.title}`}>
          <div className="day-heading">
            <strong>{day.title || `Day ${day.day}`}</strong>
            {day.summary ? <span>{day.summary}</span> : null}
          </div>
          <div className="stop-list">
            {day.stops.map((stop, stopIndex) => (
                <button
                  className={`stop-card ${
                    dayIndex === selectedDayIndex && stopIndex === selectedStopIndex
                      ? "selected"
                      : ""
                  }`}
                  type="button"
                  key={`${day.day}-${stop.name}-${stop.latitude}`}
                  onClick={() => onSelectStop(dayIndex, stopIndex)}
                >
                  <span className="stop-number">{stopIndex + 1}</span>
                  <span>
                    <strong>{stop.name}</strong>
                    <small>
                      {stop.neighborhood || stop.city} / {stop.category}
                    </small>
                    <PlaceStatus stop={stop} />
                    <em>{stop.reason}</em>
                    <SourceLine stop={stop} />
                  </span>
                </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function SourceLine({
  stop,
  compact = false,
  asLink = false,
}: {
  stop: Place;
  compact?: boolean;
  asLink?: boolean;
}) {
  const sourceType = stop.source_type;
  const allowedSource =
    sourceType === "reddit" ||
    sourceType === "google_maps" ||
    sourceType === "openstreetmap" ||
    sourceType === "official_open_data" ||
    sourceType === "curated_must_go";
  const label =
    stop.source_title ||
    (sourceType === "google_maps"
      ? "Google Maps reviews"
      : sourceType === "openstreetmap"
        ? "OpenStreetMap place details"
        : sourceType === "official_open_data"
          ? "Official open-data record"
          : sourceType === "curated_must_go"
            ? "Curated must-go France source"
        : "Reddit thread");

  if (!allowedSource) {
    return (
      <small className={`source-line missing ${compact ? "compact" : ""}`}>
        Reference: refresh OpenStreetMap or Reddit source
      </small>
    );
  }

  if (asLink && stop.source_url) {
    return (
      <a
        className={`source-line ${compact ? "compact" : ""}`}
        href={stop.source_url}
        target="_blank"
        rel="noreferrer"
      >
        Reference: {label}
      </a>
    );
  }

  return (
    <small className={`source-line ${compact ? "compact" : ""}`}>
      Reference: {label}
    </small>
  );
}

function PlaceStatus({ stop, compact = false }: { stop: Place; compact?: boolean }) {
  const mapSource = stop.map_source || sourceLabel(stop.source_type);
  const rating =
    stop.google_rating && stop.google_user_rating_count
      ? `${stop.google_rating.toFixed(1)} Google rating (${stop.google_user_rating_count} reviews)`
      : mapSource === "OpenStreetMap"
        ? "Rating: not available from OpenStreetMap"
        : "Rating: refresh map source";
  const price = stop.price_label || stop.google_price_label
    ? `Price: ${stop.price_label || stop.google_price_label}`
    : mapSource === "OpenStreetMap"
      ? "Price: not mapped in OpenStreetMap"
      : "Price: refresh map source";

  return (
    <span className={`place-status ${compact ? "compact" : ""}`}>
      <small>{rating}</small>
      <small>{price}</small>
      <small>{stop.open_status_label || "Opening hours need map-source refresh"}</small>
    </span>
  );
}

function AlternativesList({ alternatives }: { alternatives: AlternativePlace[] }) {
  return (
    <div className="alternatives-list" aria-label="Alternative places">
      <strong>Alternatives to swap in</strong>
      {alternatives.map((alt) => (
        <div className="alt-card" key={`${alt.name}-${alt.city}`}>
          <span>
            <strong>{alt.name}</strong>
            <small>
              {alt.city}
              {alt.category ? ` / ${alt.category}` : ""}
              {alt.tourist_trap_risk ? ` · ${alt.tourist_trap_risk} risk` : ""}
            </small>
            {alt.reason && <em>{alt.reason}</em>}
          </span>
          {alt.source_url ? (
            <a
              className="round-button"
              href={alt.source_url}
              target="_blank"
              rel="noreferrer"
              title="View source"
            >
              <ExternalLink size={15} />
            </a>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function sourceLabel(sourceType: string) {
  if (sourceType === "google_maps") return "Google Maps";
  if (sourceType === "openstreetmap") return "OpenStreetMap";
  if (sourceType === "official_open_data") return "Official open data";
  if (sourceType === "curated_must_go") return "Curated must-go";
  if (sourceType === "reddit") return "Reddit";
  return "source";
}
