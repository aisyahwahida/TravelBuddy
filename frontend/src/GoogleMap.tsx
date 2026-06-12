import { useEffect, useRef } from "react";
import { setOptions, importLibrary } from "@googlemaps/js-api-loader";
import type { Place } from "./types";

const API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY ?? "";
const PARIS = { lat: 48.8566, lng: 2.3522 };

let _initialized = false;
let _mapsPromise: Promise<typeof google.maps> | null = null;

function getMapsApi(): Promise<typeof google.maps> {
  if (!_mapsPromise) {
    if (!_initialized) {
      setOptions({ key: API_KEY, v: "weekly" });
      _initialized = true;
    }
    _mapsPromise = importLibrary("maps").then(() => google.maps);
  }
  return _mapsPromise;
}

type Props = {
  stops: Place[];
  selectedIndex: number;
  onSelectStop: (index: number) => void;
  startIndex?: number;
};

export default function GoogleMap({ stops, selectedIndex, onSelectStop, startIndex = 0 }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<google.maps.Map | null>(null);
  const markersRef = useRef<google.maps.marker.AdvancedMarkerElement[]>([]);
  const polylineRef = useRef<google.maps.Polyline | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;

    getMapsApi().then(async (maps) => {
      if (cancelled || !containerRef.current) return;

      const { AdvancedMarkerElement } = (await importLibrary("marker")) as google.maps.MarkerLibrary;

      const center = stops.length
        ? {
            lat: stops.reduce((s, p) => s + p.latitude, 0) / stops.length,
            lng: stops.reduce((s, p) => s + p.longitude, 0) / stops.length,
          }
        : PARIS;

      if (!mapRef.current) {
        mapRef.current = new maps.Map(containerRef.current, {
          center,
          zoom: stops.length ? 14 : 12,
          mapId: "travelbuddy_map",
          zoomControl: true,
          streetViewControl: false,
          mapTypeControl: false,
          fullscreenControl: false,
        });
      } else {
        mapRef.current.setCenter(center);
      }

      markersRef.current.forEach((m) => (m.map = null));
      markersRef.current = [];
      polylineRef.current?.setMap(null);

      if (!stops.length) return;

      const path: google.maps.LatLngLiteral[] = [];

      stops.forEach((stop, index) => {
        const pos = { lat: stop.latitude, lng: stop.longitude };
        path.push(pos);

        const pin = document.createElement("div");
        pin.className = `gmap-pin${index === selectedIndex ? " active" : ""}`;
        pin.textContent = String(startIndex + index + 1);

        const marker = new AdvancedMarkerElement({
          map: mapRef.current,
          position: pos,
          title: stop.name,
          content: pin,
        });

        marker.addListener("click", () => onSelectStop(index));
        markersRef.current.push(marker);
      });

      polylineRef.current = new maps.Polyline({
        path,
        map: mapRef.current,
        strokeColor: "#1f6f5c",
        strokeOpacity: 0.85,
        strokeWeight: 2.4,
        geodesic: true,
      });
    });

    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stops, startIndex]);

  useEffect(() => {
    markersRef.current.forEach((marker, index) => {
      const pin = marker.content as HTMLElement;
      if (pin) {
        pin.className = `gmap-pin${index === selectedIndex ? " active" : ""}`;
      }
    });

    if (mapRef.current && stops[selectedIndex]) {
      mapRef.current.panTo({
        lat: stops[selectedIndex].latitude,
        lng: stops[selectedIndex].longitude,
      });
    }
  }, [selectedIndex, stops]);

  if (!API_KEY) {
    return (
      <div className="gmap-placeholder">
        <p>Add VITE_GOOGLE_MAPS_API_KEY to frontend/.env to enable the map.</p>
      </div>
    );
  }

  return <div ref={containerRef} className="gmap-container" />;
}
