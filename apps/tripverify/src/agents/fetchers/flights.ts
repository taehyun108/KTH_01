import "server-only";
import type { FlightOption } from "@/core/types/domains";
import type { Observation } from "@/core/verification/observation";
import type { SourceReader } from "../types";
import { fetchJson, nowISO } from "@/lib/http";

export interface FlightArgs {
  origin: string; // IATA (예: ICN)
  destination: string; // IATA (예: KIX)
  date: string; // YYYY-MM-DD
  adults: number;
}

/**
 * Amadeus Self-Service (tier 2). 키(AMADEUS_CLIENT_ID/SECRET)가 있을 때만 동작.
 * 키가 없으면 빈 배열을 반환 → flight-agent 가 unverified 처리(§0-4).
 * 키 없는 항공 스케줄 공개 소스는 신뢰 가능한 것이 없어 추정하지 않는다(§0-1).
 */
export const amadeusReader: SourceReader<FlightArgs, FlightOption> = async (args) => {
  const id = process.env.AMADEUS_CLIENT_ID;
  const secret = process.env.AMADEUS_CLIENT_SECRET;
  if (!id || !secret) return [];

  const token = await getToken(id, secret);
  const url =
    `https://test.api.amadeus.com/v2/shopping/flight-offers?originLocationCode=${args.origin}` +
    `&destinationLocationCode=${args.destination}&departureDate=${args.date}` +
    `&adults=${args.adults}&max=5`;
  const data = await fetchJson<AmadeusOffers>(url, {
    headers: { authorization: `Bearer ${token}` },
  });
  const retrieved_at = nowISO();
  return (data.data ?? []).flatMap((offer) => toObs(offer, retrieved_at));
};

async function getToken(id: string, secret: string): Promise<string> {
  const res = await fetch("https://test.api.amadeus.com/v1/security/oauth2/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: `grant_type=client_credentials&client_id=${id}&client_secret=${secret}`,
  });
  if (!res.ok) throw new Error(`amadeus token HTTP ${res.status}`);
  const j = (await res.json()) as { access_token: string };
  return j.access_token;
}

interface AmadeusOffers {
  data?: {
    price?: { grandTotal?: string };
    itineraries?: {
      duration?: string;
      segments?: {
        carrierCode?: string;
        number?: string;
        departure?: { at?: string };
        arrival?: { at?: string };
      }[];
    }[];
  }[];
}

function toObs(offer: NonNullable<AmadeusOffers["data"]>[number], retrieved_at: string): Observation<FlightOption>[] {
  const it = offer.itineraries?.[0];
  const segs = it?.segments ?? [];
  const first = segs[0];
  const last = segs[segs.length - 1];
  if (!first?.departure?.at || !last?.arrival?.at) return [];
  const flight_no = `${first.carrierCode ?? ""}${first.number ?? ""}`;
  return [
    {
      value: {
        flight_no,
        depart_local: first.departure.at,
        arrive_local: last.arrival.at,
        stops: Math.max(0, segs.length - 1),
        duration_minutes: parseIsoDurationMin(it?.duration),
        ...(offer.price?.grandTotal
          ? { price_estimate_krw: Math.round(Number(offer.price.grandTotal)) }
          : {}),
      },
      source: {
        name: "Amadeus",
        url: "https://developers.amadeus.com/",
        tier: 2,
        retrieved_at,
      },
      pass: 1,
    },
  ];
}

function parseIsoDurationMin(iso?: string): number {
  if (!iso) return 0;
  const m = /PT(?:(\d+)H)?(?:(\d+)M)?/.exec(iso);
  return (Number(m?.[1] ?? 0) * 60) + Number(m?.[2] ?? 0);
}

export const liveFlightReaders: SourceReader<FlightArgs, FlightOption>[] = [amadeusReader];
