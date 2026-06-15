export type Place = {
  name: string;
  city: string;
  neighborhood: string;
  address: string;
  category: string;
  reason: string;
  local_tip: string;
  tourist_trap_risk: string;
  best_time: string;
  estimated_duration_minutes: number;
  latitude: number;
  longitude: number;
  map_source: string;
  map_url: string;
  price_label: string;
  google_maps_url: string;
  google_rating: number | null;
  google_user_rating_count: number | null;
  google_price_level: string;
  google_price_label: string;
  business_status: string;
  opening_hours: string[];
  open_now: boolean | null;
  open_status_label: string;
  tags: string[];
  source_type: string;
  source_title: string;
  source_url: string;
  confidence: number;
  photo_name: string;
  wiki_thumb_url?: string;
};

export type RecommendedForItem = {
  day_index: number;
  stop_index: number;
  replacement_score: number;
  route_delta_minutes: number;
};

export type AlternativePlace = {
  name: string;
  category: string;
  city: string;
  reason: string;
  local_tip: string;
  tourist_trap_risk: string;
  source_url: string;
  latitude: number;
  longitude: number;
  photo_name: string;
  // Contextual alternative fields (present on new-format alternatives)
  compatible_slot_types?: string[];
  recommended_for?: RecommendedForItem[];
  replacement_score?: number;
  route_delta_minutes?: number;
  distance_from_day_center_km?: number;
};

export type TravelIntent = {
  destination: string;
  duration_days: number;
  interests: string[];
  avoid: string[];
  pace: string;
  visit_day: string;
  budget: string;
  mood: string;
  travel_style: string;
  stay_location?: string;
};

export type LocationAnchor = {
  name: string;
  city?: string;
  address?: string;
  latitude: number;
  longitude: number;
  google_maps_url?: string;
};

export type EvidenceItem = {
  place_name: string;
  source_type: string;
  source_title: string;
  source_url: string;
  support_summary: string;
};

export type Itinerary = {
  title: string;
  summary: string;
  destination: string;
  themes: string[];
  stops: Place[];
  days: {
    day: number;
    title: string;
    summary: string;
    stops: Place[];
  }[];
  avoidance_notes: string[];
  practical_notes: string[];
  start_location?: LocationAnchor | null;
};

export type ChatResponse = {
  assistant_message: string;
  extracted_intent: TravelIntent;
  itinerary: Itinerary;
  session_id: string;
  evidence: EvidenceItem[];
  alternative_options: AlternativePlace[];
  is_followup?: boolean;
};
