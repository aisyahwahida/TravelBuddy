import { Component, FormEvent, useEffect, useRef, useState } from "react";

export class ErrorBoundary extends Component<{ children: React.ReactNode }, { error: Error | null }> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 32, fontFamily: "monospace", background: "#fff1f0", color: "#c0392b", minHeight: "100vh" }}>
          <h2 style={{ marginTop: 0 }}>App crashed — please report this error</h2>
          <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
            {this.state.error.message}
            {"\n\n"}
            {this.state.error.stack}
          </pre>
        </div>
      );
    }
    return this.props.children;
  }
}
import {
  ArrowRight,
  Bus,
  ChevronRight,
  ClipboardList,
  Clock,
  Download,
  ExternalLink,
  Footprints,
  History,
  LoaderCircle,
  Map as MapIcon,
  MapPin,
  PanelTop,
  Plus,
  Sparkles,
  Navigation,
  Timer,
  TramFront,
  X,
} from "lucide-react";
import type { AlternativePlace, ChatResponse, LocationAnchor, Place } from "./types";
import GoogleMap from "./GoogleMap";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000/api";
const API_ORIGIN = API_BASE.replace(/\/api\/?$/, "");

const SRC_COLOR: Record<string, string> = {
  reddit: "#d05a2b",
  google_maps: "#3a72c4",
  curated_must_go: "#bd8f33",
  official_open_data: "#bd8f33",
};

const SRC_LABEL: Record<string, string> = {
  reddit: "Reddit · r/travel",
  google_maps: "Google Places",
  curated_must_go: "Curated · France list",
  official_open_data: "Official open data",
};

type ChatMessage =
  | { role: "user"; content: string }
  | { role: "assistant"; content: string; response?: ChatResponse };

type DaySection = { day: number; title: string; summary: string; stops: Place[] };

type RouteSegment = {
  from: Pick<Place, "name" | "latitude" | "longitude"> | LocationAnchor;
  to: Place;
  distanceKm: number;
  mode: "Walk" | "Metro or bus";
  minutes: number;
};

type SavedSession = {
  id: string;
  title: string;
  timestamp: number;
  messages: ChatMessage[];
  result: ChatResponse;
  planDays: DaySection[];
  planAlts: AlternativePlace[];
};

type MobileTab = "Plan" | "Itinerary" | "Map" | "Route" | "Transit";

function haversineKm(
  from: Pick<Place, "latitude" | "longitude"> | LocationAnchor,
  to: Pick<Place, "latitude" | "longitude"> | LocationAnchor
) {
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

function buildSegments(stops: Place[], startLocation?: LocationAnchor | null): RouteSegment[] {
  const routedStops = startLocation && stops.length
    ? [{ ...startLocation }, ...stops]
    : stops;
  return routedStops.slice(0, -1).map((from, i) => {
    const to = routedStops[i + 1] as Place;
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

function displayCategory(cat: string) {
  const cleaned = cat
    .replace(/\bmust[-_ ]go\b/gi, "")
    .replace(/_/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
  if (!cleaned) return "Place";
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

function cleanUserFacingText(text: string) {
  return text
    .replace(/\bmatching\s+[a-z_]+_plan\b/gi, "")
    .replace(/\bmatching\s+[a-z_,\s]+\b(?=\s+with\b)/gi, "")
    .replace(/\bmust_go_plan\b/gi, "first-time sightseeing")
    .replace(/\b([a-z]+)_plan\b/gi, (_, name: string) => name.replace(/_/g, " "))
    .replace(/_/g, " ")
    .replace(/\s{2,}/g, " ")
    .replace(/\s+\./g, ".")
    .replace(/\s+,/g, ",")
    .trim();
}

function displaySourceLabel(type: string) {
  if (type === "reddit") return "Reddit";
  if (type === "google_maps") return "Google";
  if (type === "curated_must_go") return "Curated";
  if (type === "official_open_data") return "Open data";
  return type;
}

function cleanDayTitle(title: string, dayNumber: number) {
  if (!title) return `Day ${dayNumber}`;
  return title
    .replace(new RegExp(`^Day\\s+${dayNumber}\\b\\s*[-–—:]?\\s*`, "i"), "")
    .trim();
}

function fileNameFromDisposition(header: string | null) {
  if (!header) return "france-itinerary.pdf";
  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) return decodeURIComponent(utf8Match[1]);
  const plainMatch = header.match(/filename="?([^"]+)"?/i);
  return plainMatch?.[1] || "france-itinerary.pdf";
}

function isIOSLikeDevice() {
  if (typeof navigator === "undefined") return false;
  return (
    /iPad|iPhone|iPod/i.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

const MAPS_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY ?? "";
const wikiThumbCache = new globalThis.Map<string, string>();
const sourceThumbCache = new globalThis.Map<string, string>();

function placePhotoUrl(photoName: string, maxWidth = 400) {
  if (!photoName || !MAPS_KEY) return "";
  return `https://places.googleapis.com/v1/${photoName}/media?maxWidthPx=${maxWidth}&key=${MAPS_KEY}`;
}

function wikipediaThumbApi(sourceUrl: string) {
  if (!sourceUrl) return "";
  try {
    const url = new URL(sourceUrl);
    if (!url.hostname.includes("wikipedia.org")) return "";
    const title = decodeURIComponent(url.pathname.replace(/^\/wiki\//, "").trim());
    if (!title) return "";
    return `${url.protocol}//${url.hostname}/api/rest_v1/page/summary/${encodeURIComponent(title)}`;
  } catch {
    return "";
  }
}

function backendSourceImageApi(sourceUrl: string) {
  if (!sourceUrl) return "";
  return `${API_ORIGIN}/api/google-places/source-image?source_url=${encodeURIComponent(sourceUrl)}`;
}

function streetViewPhotoUrl(latitude: number, longitude: number, maxWidth = 400) {
  if (!MAPS_KEY || !Number.isFinite(latitude) || !Number.isFinite(longitude)) return "";
  return `https://maps.googleapis.com/maps/api/streetview?size=${maxWidth}x${Math.round(maxWidth * 0.72)}&location=${latitude},${longitude}&key=${MAPS_KEY}`;
}

function staticMapPhotoUrl(latitude: number, longitude: number, maxWidth = 400) {
  if (!MAPS_KEY || !Number.isFinite(latitude) || !Number.isFinite(longitude)) return "";
  const height = Math.round(maxWidth * 0.72);
  return `https://maps.googleapis.com/maps/api/staticmap?center=${latitude},${longitude}&zoom=15&size=${maxWidth}x${height}&markers=color:0x1f6f5c%7C${latitude},${longitude}&key=${MAPS_KEY}`;
}

function useResolvedPhotoUrl(
  photoName: string,
  sourceUrl: string,
  latitude?: number,
  longitude?: number,
  maxWidth = 400,
  wikiThumbUrl = ""
) {
  const directUrl = placePhotoUrl(photoName, maxWidth);
  const [fallbackUrl, setFallbackUrl] = useState("");
  const apiUrl = wikipediaThumbApi(sourceUrl);
  const backendApiUrl = backendSourceImageApi(sourceUrl);
  const staticMapUrl = staticMapPhotoUrl(latitude ?? NaN, longitude ?? NaN, maxWidth);

  useEffect(() => {
    if (directUrl) {
      setFallbackUrl("");
      return;
    }

    // Use backend-provided wiki thumbnail immediately (no async needed)
    if (wikiThumbUrl) {
      setFallbackUrl(wikiThumbUrl);
      return;
    }

    const wikiCached = apiUrl ? wikiThumbCache.get(apiUrl) : "";
    if (wikiCached) {
      setFallbackUrl(wikiCached);
      return;
    }

    const sourceCached = sourceUrl ? sourceThumbCache.get(sourceUrl) : "";
    if (sourceCached) {
      setFallbackUrl(sourceCached);
      return;
    }

    let cancelled = false;

    const loadFallback = async () => {
      if (apiUrl) {
        try {
          const res = await fetch(apiUrl);
          const data = res.ok ? await res.json() : null;
          const next = data?.thumbnail?.source ?? "";
          if (cancelled) return;
          if (next) {
            wikiThumbCache.set(apiUrl, next);
            setFallbackUrl(next);
            return;
          }
        } catch {
          // Try the backend source-image fallback below.
        }
      }

      if (!backendApiUrl) {
        if (!cancelled) setFallbackUrl(staticMapUrl || "");
        return;
      }

      // Show static map immediately while we try the backend scraper in parallel
      if (!cancelled && staticMapUrl) setFallbackUrl(staticMapUrl);

      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 4000);
        const res = await fetch(backendApiUrl, { signal: controller.signal });
        clearTimeout(timer);
        const data = res.ok ? await res.json() : null;
        const next = data?.image_url ?? "";
        if (cancelled) return;
        if (next) {
          sourceThumbCache.set(sourceUrl, next);
          setFallbackUrl(next);
          return;
        }
      } catch {
        // Static map already set above; nothing more to do.
      }

      if (!cancelled && !staticMapUrl) {
        setFallbackUrl("");
      }
    };

    void loadFallback();

    return () => {
      cancelled = true;
    };
  }, [backendApiUrl, directUrl, sourceUrl, apiUrl, staticMapUrl, wikiThumbUrl]);

  return directUrl || fallbackUrl;
}

function PlacePhoto({
  photoName,
  sourceUrl = "",
  latitude,
  longitude,
  alt,
  className = "stop-img",
  style,
  wikiThumbUrl = "",
}: {
  photoName: string;
  sourceUrl?: string;
  latitude?: number;
  longitude?: number;
  alt?: string;
  className?: string;
  style?: React.CSSProperties;
  wikiThumbUrl?: string;
}) {
  const url = useResolvedPhotoUrl(photoName, sourceUrl, latitude, longitude, 400, wikiThumbUrl);
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

function useIsMobile(breakpoint = 900) {
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== "undefined" ? window.innerWidth <= breakpoint : false
  );

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth <= breakpoint);
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [breakpoint]);

  return isMobile;
}

function isPermanentlyClosedPlace(place: Place) {
  return (
    place.business_status === "CLOSED_PERMANENTLY" ||
    place.open_status_label.toLowerCase().includes("permanently closed")
  );
}

function withoutClosedStops(days: DaySection[]) {
  return days
    .map((day) => ({ ...day, stops: day.stops.filter((stop) => !isPermanentlyClosedPlace(stop)) }))
    .filter((day) => day.stops.length > 0);
}

function removeNamesFromText(text: string, names: Set<string>) {
  let cleaned = text;
  names.forEach((name) => {
    cleaned = cleaned.replace(new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), "");
  });
  return cleaned.replace(/\s{2,}/g, " ").trim();
}

function sanitizeChatResponse(response: ChatResponse): ChatResponse {
  const safeStops = response.itinerary.stops.filter((stop) => !isPermanentlyClosedPlace(stop));
  const safeDays = response.itinerary.days?.length
    ? withoutClosedStops(response.itinerary.days)
    : [];
  const removedNames = new Set(
    response.itinerary.stops
      .filter((stop) => isPermanentlyClosedPlace(stop))
      .map((stop) => stop.name)
  );
  return {
    ...response,
    assistant_message: cleanUserFacingText(removeNamesFromText(response.assistant_message, removedNames)),
    itinerary: {
      ...response.itinerary,
      title: cleanUserFacingText(response.itinerary.title),
      summary: cleanUserFacingText(response.itinerary.summary),
      stops: safeStops,
      days: safeDays.map((day) => ({
        ...day,
        title: cleanUserFacingText(day.title),
        summary: cleanUserFacingText(day.summary),
      })),
    },
    evidence: response.evidence.filter((item) => !removedNames.has(item.place_name)),
  };
}

function sanitizeSavedSession(session: SavedSession): SavedSession {
  const result = sanitizeChatResponse(session.result);
  const planDays = withoutClosedStops(session.planDays);
  return {
    ...session,
    result,
    planDays,
    messages: session.messages.map((msg) =>
      msg.role === "assistant" && msg.response
        ? {
            ...msg,
            content: sanitizeChatResponse(msg.response).assistant_message,
            response: sanitizeChatResponse(msg.response),
          }
        : msg
    ),
  };
}

function loadSessions(): SavedSession[] {
  try {
    return JSON.parse(localStorage.getItem("travelbuddy_sessions") || "[]")
      .map(sanitizeSavedSession)
      .filter((session: SavedSession) => session.result.itinerary.stops.length > 0);
  } catch {
    return [];
  }
}

function persistSessions(sessions: SavedSession[]) {
  // Trim oldest sessions until the write fits in localStorage quota
  let toWrite = sessions;
  while (toWrite.length > 0) {
    try {
      localStorage.setItem("travelbuddy_sessions", JSON.stringify(toWrite));
      return;
    } catch {
      toWrite = toWrite.slice(0, Math.max(0, toWrite.length - 1));
    }
  }
  // Nothing fits — clear storage to unblock the app
  try { localStorage.removeItem("travelbuddy_sessions"); } catch { /* ignore */ }
}

function altToPlace(alt: AlternativePlace, template: Place): Place {
  return {
    ...template,           // keep photo_name, estimated_duration_minutes, etc.
    name: alt.name,
    category: alt.category,
    city: alt.city,
    neighborhood: "",
    address: "",
    reason: alt.reason,
    local_tip: alt.local_tip,
    tourist_trap_risk: alt.tourist_trap_risk,
    source_url: alt.source_url,
    source_type: "",
    source_title: "",
    latitude: alt.latitude,
    longitude: alt.longitude,
    google_rating: null,
    google_user_rating_count: null,
    google_maps_url: "",
    google_price_label: "",
    google_price_level: "",
    open_status_label: "",
    photo_name: alt.photo_name,
    // photo_name intentionally kept from template — alt has no Google photo
    map_url: "",
    opening_hours: [],
    open_now: null,
    business_status: "",
    confidence: 0,
    price_label: "",
    tags: [],
  };
}

function placeToAlt(place: Place): AlternativePlace {
  return {
    name: place.name,
    category: place.category,
    city: place.city,
    reason: place.reason,
    local_tip: place.local_tip,
    tourist_trap_risk: place.tourist_trap_risk,
    source_url: place.source_url,
    latitude: place.latitude,
    longitude: place.longitude,
    photo_name: place.photo_name,
  };
}

const WELCOME: ChatMessage = {
  role: "assistant",
  content:
    "Tell me your France city, dates, interests, and what you want to avoid. I'll build a local-first itinerary from real sourced candidates.",
};

export default function App() {
  const isMobile = useIsMobile();
  const [sessionId, setSessionId] = useState<string>(createSessionId);
  const [message, setMessage] = useState(
    "I will be in Paris for 3 days. I love food markets, bookstores, and calm local neighborhoods. Please avoid tourist traps."
  );
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME]);
  const [result, setResult] = useState<ChatResponse | null>(null);
  const [planDays, setPlanDays] = useState<DaySection[]>([]);
  const [planAlts, setPlanAlts] = useState<AlternativePlace[]>([]);
  const [selectedStopIndex, setSelectedStopIndex] = useState(0);
  const [selectedMapDayIndex, setSelectedMapDayIndex] = useState(0);
  const [activeTab, setActiveTab] = useState<"Map" | "Route" | "Transit">("Map");
  const [loading, setLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState("Planning…");
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);
  const [dragReorderOver, setDragReorderOver] = useState<string | null>(null);
  const [draggingStop, setDraggingStop] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [savedSessions, setSavedSessions] = useState<SavedSession[]>(loadSessions);
  const [mobileTab, setMobileTab] = useState<MobileTab>("Plan");
  const feedRef = useRef<HTMLDivElement | null>(null);

  const mapDaySections = planDays;
  const startLocation = result?.itinerary.start_location ?? null;

  const activeMapDay =
    mapDaySections[Math.min(selectedMapDayIndex, Math.max(mapDaySections.length - 1, 0))];
  const activeMapStops = activeMapDay?.stops ?? [];
  const selectedStop = activeMapStops[selectedStopIndex] ?? activeMapStops[0] ?? null;
  const detailPhotoUrl = useResolvedPhotoUrl(
    selectedStop?.photo_name ?? "",
    selectedStop?.source_url ?? "",
    selectedStop?.latitude,
    selectedStop?.longitude,
    600,
    selectedStop?.wiki_thumb_url ?? ""
  );
  const segments = buildSegments(activeMapStops);
  const approachSegment =
    startLocation && activeMapStops.length
      ? buildSegments([activeMapStops[0]], startLocation)[0] ?? null
      : null;

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

  const dayStartIndex = 0;

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  function saveSession(
    sid: string,
    msgs: ChatMessage[],
    res: ChatResponse,
    days: DaySection[],
    alts: AlternativePlace[]
  ) {
    const safeResponse = sanitizeChatResponse(res);
    const safeDays = withoutClosedStops(days);
    const session: SavedSession = {
      id: sid,
      title: safeResponse.extracted_intent.destination || "Untitled",
      timestamp: Date.now(),
      messages: msgs,
      result: safeResponse,
      planDays: safeDays,
      planAlts: alts,
    };
    setSavedSessions((prev) => {
      const updated = [session, ...prev.filter((s) => s.id !== sid)].slice(0, 20);
      persistSessions(updated);
      return updated;
    });
  }

  function restoreSession(session: SavedSession) {
    const safeSession = sanitizeSavedSession(session);
    setSessionId(session.id);
    setMessages(safeSession.messages);
    setResult(safeSession.result);
    setPlanDays(safeSession.planDays);
    setPlanAlts(safeSession.planAlts);
    setSelectedStopIndex(0);
    setSelectedMapDayIndex(0);
    setError(null);
    setShowHistory(false);
  }

  function deleteSession(sid: string, e: React.MouseEvent) {
    e.stopPropagation();
    setSavedSessions((prev) => {
      const updated = prev.filter((s) => s.id !== sid);
      persistSessions(updated);
      return updated;
    });
  }

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
              const chat = sanitizeChatResponse(data as ChatResponse);
              const sid = chat.session_id || sessionId;
              const days: DaySection[] = chat.itinerary.days?.length
                ? chat.itinerary.days
                : [{ day: 1, title: "Day 1", summary: "", stops: chat.itinerary.stops }];
              const alts = chat.alternative_options || [];
              setSessionId(sid);
              if (chat.is_followup) {
                setResult(chat);
                setPlanDays(days);
                setPlanAlts(alts);
                setSelectedStopIndex(0);
                setSelectedMapDayIndex(0);
                setMessages((prev) => {
                  const next = [
                    ...prev,
                    { role: "assistant" as const, content: chat.assistant_message, response: chat },
                  ];
                  saveSession(sid, next, chat, days, alts);
                  return next;
                });
              } else {
                setResult(chat);
                setPlanDays(days);
                setPlanAlts(alts);
                setSelectedStopIndex(0);
                setSelectedMapDayIndex(0);
                setMessages((prev) => {
                  const next = [
                    ...prev,
                    { role: "assistant" as const, content: chat.assistant_message, response: chat },
                  ];
                  saveSession(sid, next, chat, days, alts);
                  return next;
                });
              }
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
    setPlanDays([]);
    setPlanAlts([]);
    setSelectedStopIndex(0);
    setSelectedMapDayIndex(0);
    setError(null);
    setMobileTab("Plan");
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
      const filename = fileNameFromDisposition(res.headers.get("Content-Disposition"));
      const blob = await res.blob();
      if (!blob.size) throw new Error("PDF export failed.");
      const objectUrl = URL.createObjectURL(blob);

      const link = document.createElement("a");
      link.href = objectUrl;
      link.rel = "noopener noreferrer";
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();

      if (isIOSLikeDevice()) {
        window.setTimeout(() => {
          const popup = window.open(objectUrl, "_blank", "noopener,noreferrer");
          if (!popup) {
            window.location.assign(objectUrl);
          }
        }, 120);
      }

      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "PDF export failed.");
    } finally {
      setExporting(false);
    }
  }

  function handleDrop(alt: AlternativePlace, dayIndex: number, stopIndex: number) {
    const replaced = planDays[dayIndex].stops[stopIndex];
    setPlanDays((prev) => {
      const days = prev.map((d) => ({ ...d, stops: [...d.stops] }));
      days[dayIndex].stops[stopIndex] = altToPlace(alt, days[dayIndex].stops[stopIndex]);
      return days;
    });
    setPlanAlts((prevAlts) => [
      placeToAlt(replaced),
      ...prevAlts.filter((a) => a.name !== alt.name),
    ]);
  }

  function handleStopReorder(fromDay: number, fromStop: number, toDay: number, toStop: number) {
    if (fromDay !== toDay || fromStop === toStop) return;
    setPlanDays((prev) => {
      const days = prev.map((d) => ({ ...d, stops: [...d.stops] }));
      const stops = days[fromDay].stops;
      const [moved] = stops.splice(fromStop, 1);
      stops.splice(toStop, 0, moved);
      return days;
    });
  }

  function handleSelectStop(dayIndex: number, stopIndex: number) {
    setSelectedMapDayIndex(dayIndex);
    setSelectedStopIndex(stopIndex);
  }

  if (isMobile) {
    return (
      <MobileApp
        message={message}
        setMessage={setMessage}
        messages={messages}
        loading={loading}
        loadingMessage={loadingMessage}
        error={error}
        result={result}
        planDays={planDays}
        planAlts={planAlts}
        selectedStop={selectedStop}
        selectedStopIndex={selectedStopIndex}
        selectedMapDayIndex={selectedMapDayIndex}
        setSelectedStopIndex={setSelectedStopIndex}
        setSelectedMapDayIndex={setSelectedMapDayIndex}
        activeMapStops={activeMapStops}
        segments={segments}
        detailPhotoUrl={detailPhotoUrl}
        totalWalkMin={totalWalkMin}
        startLocation={startLocation}
        exporting={exporting}
        uniqueSources={uniqueSources}
        feedRef={feedRef}
        mobileTab={mobileTab}
        setMobileTab={setMobileTab}
        onSubmit={handleSubmit}
        onNewTrip={handleNewChat}
        onExport={handleExport}
        onSelectStop={handleSelectStop}
      />
    );
  }

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
          <div style={{ display: "flex", gap: 6 }}>
            <button
              className="icon-btn"
              type="button"
              onClick={() => setShowHistory((v) => !v)}
              title="Session history"
            >
              <History size={13} />
            </button>
            <button className="icon-btn" type="button" onClick={handleNewChat} disabled={loading}>
              <Plus size={13} />
              New trip
            </button>
          </div>
        </header>

        {/* History panel */}
        {showHistory && (
          <div className="history-panel scroll">
            <div className="hist-head">
              <span className="eyebrow">Recent sessions</span>
              <button className="icon-btn" style={{ height: 26, padding: "0 8px" }} onClick={() => setShowHistory(false)}>
                <X size={12} />
              </button>
            </div>
            {savedSessions.length === 0 ? (
              <div className="hist-empty">No saved sessions yet</div>
            ) : (
              savedSessions.map((sess) => (
                <button
                  key={sess.id}
                  className={`hist-session${sess.id === sessionId ? " active" : ""}`}
                  type="button"
                  onClick={() => restoreSession(sess)}
                >
                  <span className="hist-title">{sess.title}</span>
                  <span className="hist-meta">
                    {new Date(sess.timestamp).toLocaleDateString("en-GB", {
                      day: "numeric", month: "short", year: "numeric",
                    })}
                    {" · "}
                    {sess.planDays.reduce((n, d) => n + d.stops.length, 0)} stops
                  </span>
                  <button
                    className="hist-del"
                    type="button"
                    onClick={(e) => deleteSession(sess.id, e)}
                    title="Delete"
                  >
                    <X size={10} />
                  </button>
                </button>
              ))
            )}
          </div>
        )}

        <div className="chat-feed scroll" ref={feedRef}>
          {messages.map((msg, i) => (
            <div className={`msg ${msg.role === "user" ? "user" : "ai"}`} key={i}>
              <div className="msg-role">
                <span className={`avatar ${msg.role === "user" ? "user" : "ai"}`}>
                  {msg.role === "user" ? "Y" : "A"}
                </span>
                <span className="msg-name">{msg.role === "user" ? "You" : "Arthur"}</span>
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
                          {displaySourceLabel(type)}
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
                <span className="avatar ai">A</span>
                <span className="msg-name">Arthur</span>
              </div>
              <div className="bubble" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <LoaderCircle size={14} className="spin" style={{ color: "var(--green)" }} />
              </div>
            </div>
          )}
        </div>

        <footer className="chat-input">
          <div className="input-wrap">
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder='Refine your plan — e.g. "more street food stops", "fewer museums"…'
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  handleSubmit(e as unknown as FormEvent);
                }
              }}
            />
            <button className="send-btn" type="button" onClick={handleSubmit} disabled={loading}>
              {loading ? <LoaderCircle size={14} className="spin" /> : "Plan trip"}
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
                      <span>{result.extracted_intent.duration_days} days</span>
                      <span className="dotsep" />
                      <span>Source-backed</span>
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
                    <div className="meta-lbl">Sources</div>
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
                        <span className="day-no">Day {day.day}</span>
                        <span className="day-title">{cleanDayTitle(day.title, day.day)}</span>
                        <span className="day-sub">{day.stops.length} stops</span>
                      </div>
                      <div className="stop-list">
                        {day.stops.map((stop, stopIndex) => {
                          const isActive =
                            dayIndex === selectedMapDayIndex && stopIndex === selectedStopIndex;
                          const seg = daySegments[stopIndex];
                          const dropKey = `${dayIndex}-${stopIndex}`;
                          return (
                            <div
                              key={`${stop.name}-${stopIndex}`}
                              className={`stop${isActive ? " active" : ""}${dragOver === dropKey ? " drag-over" : ""}${dragReorderOver === dropKey ? " drag-over-reorder" : ""}${draggingStop === dropKey ? " stop-dragging" : ""}`}
                              role="button"
                              tabIndex={0}
                              draggable
                              onClick={() => handleSelectStop(dayIndex, stopIndex)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" || e.key === " ") {
                                  e.preventDefault();
                                  handleSelectStop(dayIndex, stopIndex);
                                }
                              }}
                              onDragStart={(e) => {
                                setDraggingStop(dropKey);
                                e.dataTransfer.setData("application/stop", JSON.stringify({ dayIndex, stopIndex }));
                                e.dataTransfer.effectAllowed = "move";
                              }}
                              onDragEnd={() => {
                                setDraggingStop(null);
                                setDragReorderOver(null);
                              }}
                              onDragOver={(e) => {
                                e.preventDefault();
                                if (e.dataTransfer.types.includes("application/stop")) {
                                  setDragReorderOver(dropKey);
                                } else {
                                  setDragOver(dropKey);
                                }
                              }}
                              onDragLeave={() => { setDragOver(null); setDragReorderOver(null); }}
                              onDrop={(e) => {
                                e.preventDefault();
                                setDragOver(null);
                                setDragReorderOver(null);
                                setDraggingStop(null);
                                const stopData = e.dataTransfer.getData("application/stop");
                                if (stopData) {
                                  try {
                                    const { dayIndex: fd, stopIndex: fs } = JSON.parse(stopData);
                                    handleStopReorder(fd, fs, dayIndex, stopIndex);
                                  } catch {}
                                } else {
                                  try {
                                    const alt: AlternativePlace = JSON.parse(e.dataTransfer.getData("text/plain"));
                                    handleDrop(alt, dayIndex, stopIndex);
                                  } catch {}
                                }
                              }}
                            >
                              <span className="stop-num">{stopIndex + 1}</span>
                              <PlacePhoto
                                photoName={stop.photo_name}
                                sourceUrl={stop.source_url}
                                latitude={stop.latitude}
                                longitude={stop.longitude}
                                alt={stop.name}
                                className="stop-img"
                                wikiThumbUrl={stop.wiki_thumb_url ?? ""}
                              />
                              <span className="stop-body">
                                <span className="stop-cat">
                                  <span
                                    className={`cat-chip${isMuseumCategory(stop.category) ? " museum" : ""}`}
                                  >
                                    {displayCategory(stop.category)}
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
                                      {displaySourceLabel(stop.source_type)}
                                    </a>
                                  ) : (
                                    <span
                                      className="src-link"
                                      style={{ color: SRC_COLOR[stop.source_type] ?? "var(--ink-3)" }}
                                    >
                                      <ExternalLink size={11} />
                                      {displaySourceLabel(stop.source_type)}
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
                            </div>
                          );
                        })}
                      </div>
                    </section>
                  );
                })}
              </div>

              {planAlts.length > 0 && (
                <section className="alts">
                  <div className="alts-head">
                    <h3>Alternative places</h3>
                    <span className="hint">Drag cards to swap · drag ⠿ handle to reorder</span>
                  </div>
                  <div className="alts-grid">
                    {planAlts.slice(0, 4).map((alt, idx) => (
                      <div
                        className="alt"
                        key={`${alt.name}-${alt.city}-${idx}`}
                        draggable
                        onDragStart={(e) => {
                          e.dataTransfer.setData("text/plain", JSON.stringify(alt));
                          e.dataTransfer.effectAllowed = "move";
                        }}
                      >
                          <PlacePhoto
                            photoName={alt.photo_name}
                            sourceUrl={alt.source_url}
                            latitude={alt.latitude}
                            longitude={alt.longitude}
                            alt={alt.name}
                            className="alt-img alt-drag-handle"
                          />
                        <span className="alt-body">
                          <span className={`cat-chip${isMuseumCategory(alt.category) ? " museum" : ""}`}>
                            {displayCategory(alt.category)}
                          </span>
                          <span className="alt-name">{alt.name}</span>
                          {alt.reason && <span className="alt-reason">{alt.reason}</span>}
                        </span>
                        <span className="drag-hint">
                          ↕ drag
                        </span>
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
            Route
          </span>
        </div>

        <div className="map-content scroll">
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
                  startLocation={startLocation}
                  selectedIndex={selectedStopIndex}
                  onSelectStop={setSelectedStopIndex}
                  startIndex={dayStartIndex}
                />
              </div>

              <div className="detail">
                {selectedStop ? (
                  <>
                    {startLocation && (
                      <div className="src-row" style={{ marginBottom: 8 }}>
                        <span className="src-chip">
                          <span className="src-dot" style={{ background: "#1f6f5c" }} />
                          Start from {startLocation.name}
                        </span>
                      </div>
                    )}
                    <div className={`detail-img${detailPhotoUrl ? " has-photo" : ""}`}>
                      {detailPhotoUrl ? (
                        <img
                          src={detailPhotoUrl}
                          alt={selectedStop.name}
                          loading="lazy"
                          style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
                          onError={(e) => { e.currentTarget.style.display = "none"; }}
                        />
                      ) : null}
                      <span className="detail-stop-no">{selectedStopIndex + 1}</span>
                    </div>
                    <div className="detail-cat">
                      <span className={`cat-chip${isMuseumCategory(selectedStop.category) ? " museum" : ""}`}>
                        {displayCategory(selectedStop.category)}
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
                      {(selectedStop.google_maps_url || googleMapsUrl(selectedStop)) ? (
                        <a
                          className="openbtn"
                          href={selectedStop.google_maps_url || googleMapsUrl(selectedStop)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <ExternalLink size={12} />
                          Google Maps
                        </a>
                      ) : (
                        <span className="openbtn disabled">
                          <ExternalLink size={12} />
                          Map unavailable
                        </span>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="detail-empty">Select a stop to see details</div>
                )}
              </div>

              <div className="legs">
                {segments.length > 0 || approachSegment ? (
                  <>
                    <div className="legs-head">
                      <span className="eyebrow">Between stops</span>
                    </div>
                    {approachSegment && (
                      <div className="leg">
                        <span className="leg-route">
                          <span className="leg-no">S</span>
                          <span className="leg-arrow">
                            <ArrowRight size={11} />
                          </span>
                          <span className="leg-no">1</span>
                        </span>
                        <span className="leg-mode">
                          {approachSegment.mode === "Walk" ? <Footprints size={13} /> : <Bus size={13} />}
                          {approachSegment.mode === "Walk" ? "Walk" : "Metro + walk"}
                        </span>
                        <span className="leg-time">
                          {approachSegment.minutes}
                          <span> min</span>
                        </span>
                      </div>
                    )}
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
            <RoutePanel days={mapDaySections} startLocation={startLocation} />
          )}

          {activeTab === "Transit" && (
            <TransitPanel days={mapDaySections} startLocation={startLocation} />
          )}
        </div>
      </aside>
    </div>
  );
}

// ─── Route tab ────────────────────────────────────────────────────────────────

type MobileAppProps = {
  message: string;
  setMessage: React.Dispatch<React.SetStateAction<string>>;
  messages: ChatMessage[];
  loading: boolean;
  loadingMessage: string;
  error: string | null;
  result: ChatResponse | null;
  planDays: DaySection[];
  planAlts: AlternativePlace[];
  selectedStop: Place | null;
  selectedStopIndex: number;
  selectedMapDayIndex: number;
  setSelectedStopIndex: React.Dispatch<React.SetStateAction<number>>;
  setSelectedMapDayIndex: React.Dispatch<React.SetStateAction<number>>;
  activeMapStops: Place[];
  segments: RouteSegment[];
  detailPhotoUrl: string;
  totalWalkMin: number;
  startLocation: LocationAnchor | null;
  exporting: boolean;
  uniqueSources: string[];
  feedRef: React.RefObject<HTMLDivElement | null>;
  mobileTab: MobileTab;
  setMobileTab: React.Dispatch<React.SetStateAction<MobileTab>>;
  onSubmit: (e: FormEvent) => Promise<void>;
  onNewTrip: () => void;
  onExport: () => Promise<void>;
  onSelectStop: (dayIndex: number, stopIndex: number) => void;
};

function MobileApp({
  message,
  setMessage,
  messages,
  loading,
  loadingMessage,
  error,
  result,
  planDays,
  planAlts,
  selectedStop,
  selectedStopIndex,
  selectedMapDayIndex,
  setSelectedStopIndex,
  setSelectedMapDayIndex,
  activeMapStops,
  segments,
  detailPhotoUrl,
  totalWalkMin,
  startLocation,
  exporting,
  uniqueSources,
  feedRef,
  mobileTab,
  setMobileTab,
  onSubmit,
  onNewTrip,
  onExport,
  onSelectStop,
}: MobileAppProps) {
  const sheetRef = useRef<HTMLElement | null>(null);
  const dragStateRef = useRef<{ startY: number; startOffset: number; pointerId: number | null }>({
    startY: 0,
    startOffset: 0,
    pointerId: null,
  });
  const [sheetOffsets, setSheetOffsets] = useState({ collapsed: 0, half: 0, expanded: 0 });
  const [sheetSnap, setSheetSnap] = useState<"collapsed" | "half" | "expanded">("half");
  const [sheetOffset, setSheetOffset] = useState(0);
  const [sheetDragging, setSheetDragging] = useState(false);
  const [compactPrompt, setCompactPrompt] = useState(false);
  const hasSubmittedPrompt = messages.some((msg) => msg.role === "user") || Boolean(result);

  const navItems: Array<{ tab: MobileTab; label: string; icon: typeof MapPin }> = [
    { tab: "Plan", label: "Plan", icon: PanelTop },
    { tab: "Itinerary", label: "Itinerary", icon: ClipboardList },
    { tab: "Map", label: "Map", icon: MapIcon },
    { tab: "Route", label: "Route", icon: Navigation },
    { tab: "Transit", label: "Transit", icon: TramFront },
  ];

  useEffect(() => {
    const computeOffsets = () => {
      const height = sheetRef.current?.offsetHeight ?? 0;
      if (!height) return;
      const next = {
        expanded: 0,
        half: Math.round(height * 0.34),
        collapsed: Math.max(0, height - 96),
      };
      setSheetOffsets(next);
      setSheetOffset(next[sheetSnap]);
    };

    computeOffsets();
    window.addEventListener("resize", computeOffsets);
    return () => window.removeEventListener("resize", computeOffsets);
  }, [sheetSnap]);

  useEffect(() => {
    if (!hasSubmittedPrompt) {
      setCompactPrompt(false);
    }
  }, [hasSubmittedPrompt]);

  const snapToSheet = (nextSnap: "collapsed" | "half" | "expanded") => {
    setSheetSnap(nextSnap);
    setSheetOffset(sheetOffsets[nextSnap]);
  };

  const handleSheetPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    dragStateRef.current = {
      startY: event.clientY,
      startOffset: sheetOffset,
      pointerId: event.pointerId,
    };
    setSheetDragging(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const handleSheetPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!sheetDragging || dragStateRef.current.pointerId !== event.pointerId) return;
    const delta = event.clientY - dragStateRef.current.startY;
    const nextOffset = Math.min(
      sheetOffsets.collapsed,
      Math.max(sheetOffsets.expanded, dragStateRef.current.startOffset + delta)
    );
    setSheetOffset(nextOffset);
  };

  const handleSheetPointerEnd = (event: React.PointerEvent<HTMLDivElement>) => {
    if (dragStateRef.current.pointerId !== event.pointerId) return;
    event.currentTarget.releasePointerCapture(event.pointerId);
    dragStateRef.current.pointerId = null;
    setSheetDragging(false);
    const candidates = [
      { snap: "expanded" as const, offset: sheetOffsets.expanded },
      { snap: "half" as const, offset: sheetOffsets.half },
      { snap: "collapsed" as const, offset: sheetOffsets.collapsed },
    ];
    const nearest = candidates.reduce((best, candidate) =>
      Math.abs(candidate.offset - sheetOffset) < Math.abs(best.offset - sheetOffset) ? candidate : best
    );
    snapToSheet(nearest.snap);
  };

  const handleMobileSubmit = async (e: FormEvent) => {
    await onSubmit(e);
    setCompactPrompt(true);
    snapToSheet("half");
  };

  return (
    <div className="mobile-app">
      <div className="mobile-map-stage">
        <GoogleMap
          stops={activeMapStops}
          startLocation={startLocation}
          selectedIndex={selectedStopIndex}
          onSelectStop={setSelectedStopIndex}
        />
      </div>

      <header className="mobile-brand-card">
        <div className="brand">
          <span className="brand-mark" />
          <div>
            <div className="brand-name">TravelBuddy</div>
            <div className="mobile-brand-sub">France</div>
          </div>
        </div>
      </header>

      <section
        ref={sheetRef}
        className={`mobile-sheet${sheetDragging ? " dragging" : ""} mobile-sheet-${sheetSnap}`}
        style={{ transform: `translateY(${sheetOffset}px)` }}
      >
        <div
          className="mobile-sheet-grab"
          onPointerDown={handleSheetPointerDown}
          onPointerMove={handleSheetPointerMove}
          onPointerUp={handleSheetPointerEnd}
          onPointerCancel={handleSheetPointerEnd}
        >
          <div className="mobile-sheet-handle" />
        </div>
        <div className="mobile-sheet-inner scroll" ref={mobileTab === "Plan" ? feedRef : undefined}>
          {mobileTab === "Plan" && (
            <div className="mobile-pane">
              <div className="eyebrow" style={{ marginBottom: 12 }}>Plan</div>
              <h1 className="mobile-title">Plan your France trip</h1>

              {messages.map((msg, i) => (
                <div className={`mobile-msg ${msg.role === "user" ? "user" : "ai"}`} key={i}>
                  <div className="msg-role">
                    <span className={`avatar ${msg.role === "user" ? "user" : "ai"}`}>
                      {msg.role === "user" ? "Y" : "A"}
                    </span>
                    <span className="msg-name">{msg.role === "user" ? "You" : "Arthur"}</span>
                  </div>
                  <div className={`mobile-bubble ${msg.role === "user" ? "user" : "ai"}`}>
                    {msg.content}
                  </div>
                </div>
              ))}

              {loading && (
                <div className="mobile-msg ai">
                  <div className="msg-role">
                    <span className="avatar ai">A</span>
                    <span className="msg-name">Arthur</span>
                  </div>
                  <div className="mobile-status">
                    <LoaderCircle size={15} className="spin" />
                    {loadingMessage}
                  </div>
                </div>
              )}

              <form className={`mobile-input-card${compactPrompt ? " compact" : ""}`} onSubmit={handleMobileSubmit}>
                <textarea
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  onFocus={() => setCompactPrompt(false)}
                  placeholder='Refine your plan — e.g. "more street food stops"'
                />
                <button className="mobile-send-btn" type="submit" disabled={loading}>
                  {loading ? <LoaderCircle size={16} className="spin" /> : "Generate plan"}
                  <ArrowRight size={16} />
                </button>
              </form>

              {error && <div className="error-note" style={{ margin: 0 }}>{error}</div>}
            </div>
          )}

          {mobileTab === "Itinerary" && (
            result ? (
              <div className="mobile-pane">
                <div className="mobile-summary-card">
                  <div className="eyebrow">Itinerary</div>
                  <h2>{result.extracted_intent.destination}</h2>
                  <p>{result.assistant_message}</p>
                  <div className="mobile-stat-row">
                    <span>{result.itinerary.stops.length} stops</span>
                    <span>{result.extracted_intent.duration_days} days</span>
                    <span>{totalWalkMin} min walk</span>
                  </div>
                  <button
                    className="export-btn mobile-export-btn"
                    type="button"
                    onClick={onExport}
                    disabled={exporting}
                  >
                    {exporting ? <LoaderCircle size={14} className="spin" /> : <Download size={14} />}
                    Export PDF
                  </button>
                </div>

                <div className="mobile-source-row">
                  {uniqueSources.map((type) => (
                    <span className="src-chip" key={type}>
                      <span className="src-dot" style={{ background: SRC_COLOR[type] }} />
                      {displaySourceLabel(type)}
                    </span>
                  ))}
                </div>

                {planDays.map((day, dayIndex) => (
                  <section className="mobile-day-card" key={`${day.day}-${day.title}`}>
                    <div className="mobile-day-head">
                      <span className="day-no">Day {day.day}</span>
                      <div>
                        <div className="mobile-day-title">{cleanDayTitle(day.title, day.day)}</div>
                        <div className="mobile-day-sub">{day.stops.length} stops</div>
                      </div>
                    </div>
                    <div className="mobile-stop-list">
                      {day.stops.map((stop, stopIndex) => (
                        <button
                          key={`${stop.name}-${stopIndex}`}
                          className="mobile-stop-card"
                          type="button"
                          onClick={() => {
                            onSelectStop(dayIndex, stopIndex);
                            setMobileTab("Map");
                          }}
                        >
                          <PlacePhoto
                            photoName={stop.photo_name}
                            sourceUrl={stop.source_url}
                            latitude={stop.latitude}
                            longitude={stop.longitude}
                            alt={stop.name}
                            className="mobile-stop-img"
                            wikiThumbUrl={stop.wiki_thumb_url ?? ""}
                          />
                          <div className="mobile-stop-body">
                            <span className={`cat-chip${isMuseumCategory(stop.category) ? " museum" : ""}`}>
                              {displayCategory(stop.category)}
                            </span>
                            <span className="mobile-stop-name">{stop.name}</span>
                            <span className="mobile-stop-meta">
                              {stop.google_rating ? (
                                <>
                                  <Stars rating={stop.google_rating} />
                                  {stop.google_rating.toFixed(1)}
                                </>
                              ) : (
                                stop.local_tip || stop.reason
                              )}
                            </span>
                          </div>
                          <ChevronRight size={16} className="chev" />
                        </button>
                      ))}
                    </div>
                  </section>
                ))}

                {planAlts.length > 0 && (
                  <section className="mobile-day-card">
                    <div className="mobile-day-title" style={{ marginBottom: 12 }}>Alternative places</div>
                    <div className="mobile-alt-grid">
                      {planAlts.slice(0, 4).map((alt, idx) => (
                        <div className="alt" key={`${alt.name}-${idx}`}>
                          <PlacePhoto
                            photoName={alt.photo_name}
                            sourceUrl={alt.source_url}
                            latitude={alt.latitude}
                            longitude={alt.longitude}
                            alt={alt.name}
                            className="alt-img"
                          />
                          <span className="alt-body">
                            <span className={`cat-chip${isMuseumCategory(alt.category) ? " museum" : ""}`}>
                              {displayCategory(alt.category)}
                            </span>
                            <span className="alt-name">{alt.name}</span>
                          </span>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              </div>
            ) : (
              <div className="mobile-empty-state">
                <ClipboardList size={28} />
                <p>Generate a plan first to see the itinerary.</p>
              </div>
            )
          )}

          {mobileTab === "Map" && (
            selectedStop ? (
              <div className="mobile-pane">
                <div className="mobile-map-chip-row">
                  {planDays.map((day, index) => (
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

                <div className="mobile-detail-card">
                  {startLocation && (
                    <div className="mobile-source-row" style={{ marginBottom: 10 }}>
                      <span className="src-chip">
                        <span className="src-dot" style={{ background: "#1f6f5c" }} />
                        Start from {startLocation.name}
                      </span>
                    </div>
                  )}
                  <div className={`detail-img mobile-detail-img${detailPhotoUrl ? " has-photo" : ""}`}>
                    {detailPhotoUrl ? (
                      <img
                        src={detailPhotoUrl}
                        alt={selectedStop.name}
                        loading="lazy"
                        style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
                        onError={(e) => {
                          e.currentTarget.style.display = "none";
                        }}
                      />
                    ) : null}
                    <span className="detail-stop-no">{selectedStopIndex + 1}</span>
                  </div>

                  <span className={`cat-chip${isMuseumCategory(selectedStop.category) ? " museum" : ""}`}>
                    {displayCategory(selectedStop.category)}
                  </span>
                  <div className="detail-name" style={{ marginTop: 10 }}>{selectedStop.name}</div>
                  <div className="detail-sub">{selectedStop.neighborhood || selectedStop.city}</div>

                  {(selectedStop.local_tip || selectedStop.reason) && (
                    <div className="detail-why">
                      <div className="why-lbl">
                        <span className="eyebrow">Why it's here</span>
                      </div>
                      <div className="why-quote">{selectedStop.local_tip || selectedStop.reason}</div>
                    </div>
                  )}

                  <div className="detail-foot">
                    {segments[selectedStopIndex] ? (
                      <span className="walkpill">
                        {segments[selectedStopIndex].mode === "Walk" ? <Footprints size={11} /> : <Bus size={11} />}
                        {segments[selectedStopIndex].minutes} min to next
                      </span>
                    ) : (
                      <span style={{ fontSize: 11, color: "var(--ink-4)", fontFamily: "var(--mono)" }}>
                        Last stop
                      </span>
                    )}
                    <a
                      className="openbtn"
                      href={selectedStop.google_maps_url || googleMapsUrl(selectedStop)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <ExternalLink size={12} />
                      Google Maps
                    </a>
                  </div>
                </div>

                <div className="mobile-selector-list">
                  {activeMapStops.map((stop, stopIndex) => (
                    <button
                      key={`${stop.name}-${stopIndex}`}
                      className={`mobile-stop-card compact${stopIndex === selectedStopIndex ? " active" : ""}`}
                      type="button"
                      onClick={() => setSelectedStopIndex(stopIndex)}
                    >
                      <span className="stop-num">{stopIndex + 1}</span>
                      <div className="mobile-stop-body">
                        <span className="mobile-stop-name">{stop.name}</span>
                        <span className="mobile-stop-meta">{displayCategory(stop.category)}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="mobile-empty-state">
                <MapIcon size={28} />
                <p>Generate a plan first to explore it on the map.</p>
              </div>
            )
          )}

          {mobileTab === "Route" && <RoutePanel days={planDays} startLocation={startLocation} />}
          {mobileTab === "Transit" && <TransitPanel days={planDays} startLocation={startLocation} />}
        </div>
      </section>

      <nav className="mobile-bottom-nav">
        {navItems.map(({ tab, label, icon: Icon }) => (
          <button
            key={tab}
            className={`mobile-nav-btn${mobileTab === tab ? " active" : ""}`}
            type="button"
            onClick={() => setMobileTab(tab)}
          >
            <Icon size={20} />
            <span>{label}</span>
          </button>
        ))}
        <button className="mobile-nav-btn" type="button" onClick={onNewTrip}>
          <Plus size={20} />
          <span>New Trip</span>
        </button>
      </nav>
    </div>
  );
}

type DaySection2 = { day: number; title: string; summary: string; stops: Place[] };

function RoutePanel({ days, startLocation }: { days: DaySection2[]; startLocation?: LocationAnchor | null }) {
  if (!days.length) {
    return (
      <div className="tab-panel scroll tab-empty">
        <Navigation size={28} />
        <p>Generate a plan to see the full route breakdown.</p>
      </div>
    );
  }

  const allSegs = days.map((day) => ({ day, segs: buildSegments(day.stops, startLocation) }));
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
              Day {day.day}
            </span>
            <span style={{ fontFamily: "var(--sans)", fontSize: 16, fontWeight: 600 }}>
              {cleanDayTitle(day.title, day.day)}
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

function TransitPanel({ days, startLocation }: { days: DaySection2[]; startLocation?: LocationAnchor | null }) {
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
        const segs = buildSegments(day.stops, startLocation);
        let clock = 9 * 60;

        return (
          <div className="transit-day" key={day.day}>
            <div className="route-day-head">
              <span className="day-no" style={{ fontSize: 9, padding: "4px 8px" }}>
              Day {day.day}
              </span>
              <span style={{ fontFamily: "var(--sans)", fontSize: 16, fontWeight: 600 }}>
                {cleanDayTitle(day.title, day.day)}
              </span>
            </div>

            <div className="timeline">
              {startLocation && day.stops.length > 0 && segs[0] && (
                <div className="tl-leg">
                  <div className="tl-time tl-time-sm">{toHHMM(clock)}</div>
                  <div className="tl-dot-col">
                    <div className="tl-leg-icon">
                      {segs[0].mode === "Walk" ? <Footprints size={10} /> : <Bus size={10} />}
                    </div>
                    <div className="tl-line" />
                  </div>
                  <div className="tl-leg-desc">
                    {startLocation.name} to {day.stops[0].name} · {segs[0].mode === "Walk" ? "Walk" : "Metro or bus"} · {segs[0].minutes} min
                  </div>
                </div>
              )}
              {day.stops.map((stop, i) => {
                const arrivalTime = clock + (startLocation && i === 0 && segs[0] ? segs[0].minutes : 0);
                const stayMin = stop.estimated_duration_minutes || 60;
                const departTime = arrivalTime + stayMin;
                const seg = segs[startLocation ? i + 1 : i];
                clock = departTime + (seg?.minutes ?? 0);

                return (
                  <div key={`${stop.name}-${i}`}>
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
                            {displayCategory(stop.category)}
                          </span>
                          <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-3)" }}>
                            {stayMin} min stay · depart {toHHMM(departTime)}
                          </span>
                        </div>
                      </div>
                    </div>

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
